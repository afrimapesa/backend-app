"""Remittance comparison (T12): latest quotes for a corridor, ranked for an amount.

The expensive part (latest quote per provider + the mid-market rate) is a per-corridor
snapshot cached in Redis for ``CACHE_TTL`` seconds and dropped whenever new quotes are
stored. Ranking a specific amount is cheap and done per request with the engine.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.cache import cache

from apps.fx.services import MidRate, latest_mid
from apps.reference.models import Corridor

from . import engine
from .models import ProviderQuote

CACHE_TTL = 60  # seconds; quotes refresh every 5 min at best, so this is never far behind
QUOTE_LOOKBACK = timedelta(hours=24)  # older quotes are not shown at all


@dataclass(frozen=True)
class ProviderInfo:
    slug: str
    name: str
    website: str


@dataclass(frozen=True)
class CorridorSnapshot:
    corridor_code: str
    send_currency: str
    receive_currency: str
    send_minor_units: int
    receive_minor_units: int
    mid: MidRate | None
    quotes: tuple[engine.ProviderQuote, ...]
    providers: dict[str, ProviderInfo]
    sample_providers: frozenset[str]
    providers_on_route: int


@dataclass(frozen=True)
class Comparison:
    snapshot: CorridorSnapshot
    amount: Decimal
    results: list[engine.QuoteResult]

    @property
    def mid_payout(self) -> Decimal | None:
        if self.snapshot.mid is None:
            return None
        return (self.amount * self.snapshot.mid.rate).quantize(
            Decimal(1).scaleb(-self.snapshot.receive_minor_units)
        )

    @property
    def sample(self) -> bool:
        mid_sample = self.snapshot.mid is not None and self.snapshot.mid.sample
        return mid_sample or any(r.provider in self.snapshot.sample_providers for r in self.results)


def cache_key(corridor_id: int) -> str:
    return f"remittance:compare:v1:{corridor_id}"


def invalidate(corridor_ids: Iterable[int]) -> None:
    cache.delete_many([cache_key(cid) for cid in set(corridor_ids)])


def compare(corridor: Corridor, amount: Decimal, *, now: datetime) -> Comparison:
    """Rank the corridor's latest provider quotes for ``amount`` (top 5)."""
    snap = snapshot(corridor, now=now)
    results = (
        engine.rank_quotes(
            snap.quotes,
            amount,
            snap.mid.rate,
            now,
            send_minor_units=snap.send_minor_units,
            receive_minor_units=snap.receive_minor_units,
        )
        if snap.mid is not None
        else []  # no fresh reference rate: nothing can be priced honestly
    )
    return Comparison(snapshot=snap, amount=amount, results=results)


def snapshot(corridor: Corridor, *, now: datetime) -> CorridorSnapshot:
    key = cache_key(corridor.pk)
    cached = cache.get(key)
    if cached is not None:
        return cached
    snap = _build_snapshot(corridor, now=now)
    cache.set(key, snap, CACHE_TTL)
    return snap


def _build_snapshot(corridor: Corridor, *, now: datetime) -> CorridorSnapshot:
    latest = list(
        ProviderQuote.objects.filter(
            corridor=corridor,
            provider__is_active=True,
            observed_at__gte=now - QUOTE_LOOKBACK,
            observed_at__lte=now,
        )
        .select_related("provider")
        .order_by("provider_id", "-observed_at")
        .distinct("provider_id")
    )
    return CorridorSnapshot(
        corridor_code=corridor.code,
        send_currency=corridor.send_currency_id,
        receive_currency=corridor.receive_currency_id,
        send_minor_units=corridor.send_currency.minor_units,
        receive_minor_units=corridor.receive_currency.minor_units,
        mid=latest_mid(corridor.send_currency_id, corridor.receive_currency_id, at=now),
        quotes=tuple(q.to_engine() for q in latest),
        providers={
            q.provider.slug: ProviderInfo(q.provider.slug, q.provider.name, q.provider.website)
            for q in latest
        },
        sample_providers=frozenset(
            q.provider.slug for q in latest if q.source == ProviderQuote.Source.SAMPLE
        ),
        providers_on_route=corridor.providers.filter(is_active=True).count(),
    )
