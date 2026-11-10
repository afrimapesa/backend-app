"""Currency movers: how each receiving-country currency has moved against a base currency.

Built from the same daily history as the trend chart. Cached briefly because rates arrive
every few minutes at most and the news page calls it on every load.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.cache import cache

from apps.reference.models import Country, Currency

from .history import daily_history

CACHE_TTL = 300


@dataclass(frozen=True)
class Mover:
    currency: str
    name: str
    country: str
    rate: Decimal  # latest: 1 base = rate currency
    change_1d: Decimal | None  # fractional change in the rate since the previous day
    change_period: Decimal | None  # since the first day of the period
    points: list[tuple[date, Decimal]]
    sample: bool


def movers(base: str, *, days: int, today: date) -> list[Mover]:
    key = f"fx:movers:v1:{base}:{days}:{today.isoformat()}"
    cached = cache.get(key)
    if cached is None:
        cached = _build(base, days=days, today=today)
        cache.set(key, cached, CACHE_TTL)
    return cached


def _build(base: str, *, days: int, today: date) -> list[Mover]:
    countries = (
        Country.objects.filter(is_receiving=True, is_active=True)
        .exclude(currency_id=base)
        .order_by("name")
    )
    names = dict(Currency.objects.values_list("code", "name"))
    result = []
    seen = set()
    for country in countries:
        code = country.currency_id
        if code in seen:
            continue
        seen.add(code)
        series = daily_history(base, code, days=days, today=today)
        if not series.points:
            continue
        rates = [r for _, r in series.points]
        result.append(
            Mover(
                currency=code,
                name=names.get(code, code),
                country=country.name,
                rate=rates[-1],
                change_1d=_change(rates[-2], rates[-1]) if len(rates) > 1 else None,
                change_period=_change(rates[0], rates[-1]) if len(rates) > 1 else None,
                points=series.points,
                sample=series.sample,
            )
        )
    return result


def _change(old: Decimal, new: Decimal) -> Decimal:
    return (new / old - 1).quantize(Decimal("0.000001"))
