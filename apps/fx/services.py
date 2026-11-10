"""Mid-market rate lookups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .models import FxMidRate

# FX feeds refresh every 5 minutes; anything older than this is not a usable reference.
DEFAULT_MAX_AGE = timedelta(minutes=30)
PIVOT = "USD"


@dataclass(frozen=True)
class MidRate:
    rate: Decimal
    observed_at: datetime  # the older observation, for a cross rate
    sample: bool  # any input came from preview sample data


def latest_mid(
    base: str, quote: str, *, at: datetime, max_age: timedelta = DEFAULT_MAX_AGE
) -> MidRate | None:
    """Mid-market rate for 1 ``base`` in ``quote`` as of ``at``, or None if no fresh rate.

    Uses a direct observation when available, otherwise derives a cross rate through USD
    (strategy doc §3.1: NGN/KES = 1/(USD/NGN) x (USD/KES)).
    """
    if base == quote:
        return MidRate(Decimal(1), at, sample=False)
    direct = _latest(base, quote, at, max_age)
    if direct is not None:
        return direct
    if PIVOT in (base, quote):
        return None
    usd_base = _latest(PIVOT, base, at, max_age)
    usd_quote = _latest(PIVOT, quote, at, max_age)
    if usd_base is None or usd_quote is None:
        return None
    return MidRate(
        rate=usd_quote.rate / usd_base.rate,
        observed_at=min(usd_base.observed_at, usd_quote.observed_at),
        sample=usd_base.sample or usd_quote.sample,
    )


def latest_mid_rate(
    base: str, quote: str, *, at: datetime, max_age: timedelta = DEFAULT_MAX_AGE
) -> Decimal | None:
    """Just the rate from :func:`latest_mid`."""
    mid = latest_mid(base, quote, at=at, max_age=max_age)
    return mid.rate if mid else None


def _latest(base: str, quote: str, at: datetime, max_age: timedelta) -> MidRate | None:
    row = (
        FxMidRate.objects.filter(
            base_id=base, quote_id=quote, observed_at__lte=at, observed_at__gte=at - max_age
        )
        .order_by("-observed_at")
        .values_list("rate", "observed_at", "source")
        .first()
    )
    if row is None:
        return None
    rate, observed_at, source = row
    return MidRate(rate, observed_at, sample=source == FxMidRate.Source.SAMPLE)
