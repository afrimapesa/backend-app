"""Remittance cost calculation engine (strategy doc §3.1).

Pure functions over ``Decimal`` with no database access, so the same logic serves the
compare API, ingestion sanity checks and tests.

Definitions, for a transfer of amount ``A`` in the sending currency:

* ``F_transfer = F_flat + A * F_pct``                (explicit fee, sending currency)
* ``A_net      = (A - F_transfer) * FX_prov``        (payout, receiving currency)
* ``effective_rate = A_net / A``
* ``total_cost = A - A_net / FX_mid``                (true cost vs mid-market, sending currency)

Rounding: fees round half-up to the sending currency's minor units (what the customer
is charged); payouts round down to the receiving currency's minor units (never overstate
what the recipient gets).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

TOP_N = 5
STALE_MULTIPLIER = 2  # exit criterion E05: stale when older than 2x the update interval
RATE_PLACES = Decimal("0.000001")
ZERO = Decimal(0)


def _decimal(value: Decimal | int | str, name: str) -> Decimal:
    if isinstance(value, float):
        raise TypeError(f"{name} must be Decimal, int or str, not float (precision loss)")
    return Decimal(value)


def _minor(places: int) -> Decimal:
    return Decimal(1).scaleb(-places)


@dataclass(frozen=True)
class FeeSchedule:
    """Explicit transfer fee. ``pct`` is a fraction: ``Decimal("0.015")`` means 1.5%."""

    flat: Decimal = ZERO
    pct: Decimal = ZERO

    def __post_init__(self) -> None:
        object.__setattr__(self, "flat", _decimal(self.flat, "flat"))
        object.__setattr__(self, "pct", _decimal(self.pct, "pct"))
        if self.flat < 0:
            raise ValueError("flat fee cannot be negative")
        if not ZERO <= self.pct < 1:
            raise ValueError("pct fee must be a fraction in [0, 1)")

    def fee_for(self, amount: Decimal, minor_units: int = 2) -> Decimal:
        fee = self.flat + amount * self.pct
        return fee.quantize(_minor(minor_units), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ProviderQuote:
    """One provider's offer on one corridor at a point in time."""

    provider: str
    fx_rate: Decimal  # receiving-currency units per 1 sending-currency unit
    fee: FeeSchedule
    observed_at: datetime
    update_interval: timedelta
    transfer_time: timedelta | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fx_rate", _decimal(self.fx_rate, "fx_rate"))
        if self.fx_rate <= 0:
            raise ValueError("fx_rate must be positive")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        for name in ("min_amount", "max_amount"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _decimal(value, name))
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount cannot exceed max_amount")

    def accepts(self, amount: Decimal) -> bool:
        if self.min_amount is not None and amount < self.min_amount:
            return False
        return self.max_amount is None or amount <= self.max_amount

    def is_stale(self, now: datetime) -> bool:
        return now - self.observed_at > self.update_interval * STALE_MULTIPLIER


@dataclass(frozen=True)
class QuoteResult:
    provider: str
    amount: Decimal
    transfer_fee: Decimal
    fx_rate: Decimal
    fx_mid: Decimal
    net_payout: Decimal
    effective_rate: Decimal
    fx_markup_pct: Decimal
    total_cost: Decimal
    total_cost_pct: Decimal
    transfer_time: timedelta | None
    observed_at: datetime
    is_stale: bool
    rank: int | None = None


def calculate(
    quote: ProviderQuote,
    amount: Decimal,
    fx_mid: Decimal,
    now: datetime,
    *,
    send_minor_units: int = 2,
    receive_minor_units: int = 2,
) -> QuoteResult | None:
    """Price ``amount`` against one quote. Returns ``None`` if the quote can't serve it
    (outside the provider's limits, or the fee consumes the whole amount)."""
    amount = _decimal(amount, "amount")
    fx_mid = _decimal(fx_mid, "fx_mid")
    if amount <= 0:
        raise ValueError("amount must be positive")
    if fx_mid <= 0:
        raise ValueError("fx_mid must be positive")

    if not quote.accepts(amount):
        return None
    fee = quote.fee.fee_for(amount, send_minor_units)
    if fee >= amount:
        return None

    net_payout = ((amount - fee) * quote.fx_rate).quantize(
        _minor(receive_minor_units), rounding=ROUND_DOWN
    )
    total_cost = (amount - net_payout / fx_mid).quantize(
        _minor(send_minor_units), rounding=ROUND_HALF_UP
    )
    return QuoteResult(
        provider=quote.provider,
        amount=amount,
        transfer_fee=fee,
        fx_rate=quote.fx_rate,
        fx_mid=fx_mid,
        net_payout=net_payout,
        effective_rate=(net_payout / amount).quantize(RATE_PLACES),
        fx_markup_pct=((fx_mid - quote.fx_rate) / fx_mid).quantize(RATE_PLACES),
        total_cost=total_cost,
        total_cost_pct=(total_cost / amount).quantize(RATE_PLACES),
        transfer_time=quote.transfer_time,
        observed_at=quote.observed_at,
        is_stale=quote.is_stale(now),
    )


def _sort_key(result: QuoteResult) -> tuple:
    # Best payout first; ties go to lower fee, then faster delivery, then name (deterministic).
    speed = result.transfer_time if result.transfer_time is not None else timedelta.max
    return (-result.net_payout, result.transfer_fee, speed, result.provider)


def rank_quotes(
    quotes: Iterable[ProviderQuote],
    amount: Decimal,
    fx_mid: Decimal,
    now: datetime,
    *,
    limit: int | None = TOP_N,
    send_minor_units: int = 2,
    receive_minor_units: int = 2,
) -> list[QuoteResult]:
    """Rank quotes by net payout (``A_net``) descending and return the top ``limit``."""
    results = [
        result
        for quote in quotes
        if (
            result := calculate(
                quote,
                amount,
                fx_mid,
                now,
                send_minor_units=send_minor_units,
                receive_minor_units=receive_minor_units,
            )
        )
        is not None
    ]
    results.sort(key=_sort_key)
    if limit is not None:
        results = results[:limit]
    return [replace(result, rank=rank) for rank, result in enumerate(results, start=1)]
