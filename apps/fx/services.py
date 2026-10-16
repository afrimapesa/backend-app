"""Mid-market rate lookups."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from .models import FxMidRate

# FX feeds refresh every 5 minutes; anything older than this is not a usable reference.
DEFAULT_MAX_AGE = timedelta(minutes=30)
PIVOT = "USD"


def latest_mid_rate(
    base: str, quote: str, *, at: datetime, max_age: timedelta = DEFAULT_MAX_AGE
) -> Decimal | None:
    """Mid-market rate for 1 ``base`` in ``quote`` as of ``at``, or None if no fresh rate.

    Uses a direct observation when available, otherwise derives a cross rate through USD
    (strategy doc §3.1: NGN/KES = 1/(USD/NGN) x (USD/KES)).
    """
    if base == quote:
        return Decimal(1)
    direct = _latest(base, quote, at, max_age)
    if direct is not None:
        return direct
    if PIVOT in (base, quote):
        return None
    usd_base = _latest(PIVOT, base, at, max_age)
    usd_quote = _latest(PIVOT, quote, at, max_age)
    if usd_base is None or usd_quote is None:
        return None
    return usd_quote / usd_base


def _latest(base: str, quote: str, at: datetime, max_age: timedelta) -> Decimal | None:
    return (
        FxMidRate.objects.filter(
            base_id=base, quote_id=quote, observed_at__lte=at, observed_at__gte=at - max_age
        )
        .order_by("-observed_at")
        .values_list("rate", flat=True)
        .first()
    )
