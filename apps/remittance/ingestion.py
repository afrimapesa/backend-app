"""Base class for provider quote adapters (Wise, Remitly, ...).

A concrete adapter sets ``source`` and ``provider_slug`` and implements ``fetch`` and
``normalize`` (returning :class:`QuoteRecord`); validation and storage are shared.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.fx.services import latest_mid_rate
from apps.ingestion.base import Adapter, RecordRejected
from apps.ingestion.models import IngestionRun
from apps.ingestion.validators import check_against_mid
from apps.reference.models import Corridor

from .models import ProviderQuote

CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class QuoteRecord:
    send_country: str  # e.g. "GB"
    receive_country: str  # e.g. "NG"
    observed_at: datetime
    fx_rate: Decimal
    fee_flat: Decimal = Decimal(0)
    fee_pct: Decimal = Decimal(0)
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    transfer_time: timedelta | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


class ProviderQuoteAdapter[RawT](Adapter[RawT, QuoteRecord]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._corridors: dict[tuple[str, str], Corridor] | None = None

    def validate(self, record: QuoteRecord) -> None:
        corridor = self.corridor_for(record)
        if record.observed_at.tzinfo is None:
            raise RecordRejected("observed_at is not timezone-aware")
        if record.observed_at > timezone.now() + CLOCK_SKEW:
            raise RecordRejected(f"observed_at {record.observed_at.isoformat()} is in the future")
        if record.fee_flat < 0:
            raise RecordRejected(f"Negative flat fee {record.fee_flat}")
        if not Decimal(0) <= record.fee_pct < 1:
            raise RecordRejected(f"Fee percentage {record.fee_pct} is not a fraction in [0, 1)")
        if (
            record.min_amount is not None
            and record.max_amount is not None
            and record.min_amount > record.max_amount
        ):
            raise RecordRejected(f"min_amount {record.min_amount} > max_amount {record.max_amount}")

        mid = latest_mid_rate(
            corridor.send_currency_id, corridor.receive_currency_id, at=record.observed_at
        )
        check_against_mid(record.fx_rate, mid)

    def store(self, records: Sequence[QuoteRecord], run: IngestionRun) -> int:
        if run.provider_id is None:
            raise RuntimeError(f"{type(self).__name__} must set provider_slug")
        rows = [
            ProviderQuote(
                provider_id=run.provider_id,
                corridor=self.corridor_for(r),
                observed_at=r.observed_at,
                fx_rate=r.fx_rate,
                fee_flat=r.fee_flat,
                fee_pct=r.fee_pct,
                min_amount=r.min_amount,
                max_amount=r.max_amount,
                transfer_time=r.transfer_time,
                raw=r.raw,
                source=ProviderQuote.Source.ADAPTER,
                ingestion_run=run,
            )
            for r in records
        ]
        # A re-delivered observation (same provider, corridor, timestamp) is a no-op.
        ProviderQuote.objects.bulk_create(rows, ignore_conflicts=True)
        return len(rows)

    def corridor_for(self, record: QuoteRecord) -> Corridor:
        if self._corridors is None:
            self._corridors = {
                (c.send_country_id, c.receive_country_id): c
                for c in Corridor.objects.filter(providers__slug=self.provider_slug, is_active=True)
            }
        try:
            return self._corridors[(record.send_country, record.receive_country)]
        except KeyError:
            raise RecordRejected(
                f"{self.provider_slug} does not serve {record.send_country}->"
                f"{record.receive_country}"
            ) from None

    def describe(self, record: QuoteRecord) -> str:
        return f"{record.send_country}->{record.receive_country} @ {record.fx_rate}"
