"""Sanity checks shared by adapters (T09)."""

from __future__ import annotations

from decimal import Decimal

from .base import RecordRejected

# A provider rate this far below mid-market is almost certainly a parsing error (the
# worst real-world margins are ~5-8%). Rates *above* mid-market happen only as small
# promotions, so the tolerance on that side is much tighter.
MAX_BELOW_MID = Decimal("0.10")
MAX_ABOVE_MID = Decimal("0.03")


def check_against_mid(
    fx_rate: Decimal,
    fx_mid: Decimal | None,
    *,
    max_below: Decimal = MAX_BELOW_MID,
    max_above: Decimal = MAX_ABOVE_MID,
) -> None:
    """Reject a provider rate that is implausibly far from the mid-market rate."""
    if fx_mid is None:
        raise RecordRejected("No fresh mid-market rate to validate against")
    if fx_rate <= 0:
        raise RecordRejected(f"Non-positive rate {fx_rate}")
    deviation = (fx_rate - fx_mid) / fx_mid
    if deviation < -max_below:
        raise RecordRejected(
            f"Rate {fx_rate} is {-deviation:.2%} below mid-market {fx_mid:.6f} "
            f"(limit {max_below:.0%})"
        )
    if deviation > max_above:
        raise RecordRejected(
            f"Rate {fx_rate} is {deviation:.2%} above mid-market {fx_mid:.6f} "
            f"(limit {max_above:.0%})"
        )
