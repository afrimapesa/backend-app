"""Base class for mid-market FX feed adapters (Open Exchange Rates, ExchangeRate-API, ...).

A concrete adapter sets ``source``/``fx_source`` and implements ``fetch`` and ``normalize``
(returning :class:`RateRecord`); validation and storage are shared.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar

from django.utils import timezone

from apps.ingestion.base import Adapter, RecordRejected
from apps.ingestion.models import IngestionRun
from apps.reference.models import Currency

from .models import FxMidRate

CLOCK_SKEW = timedelta(minutes=5)
MAX_AGE = timedelta(days=1)


@dataclass(frozen=True)
class RateRecord:
    base: str
    quote: str
    observed_at: datetime
    rate: Decimal


class FxRateAdapter[RawT](Adapter[RawT, RateRecord]):
    fx_source: ClassVar[str]  # a FxMidRate.Source value

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._currencies: set[str] | None = None

    def validate(self, record: RateRecord) -> None:
        if self._currencies is None:
            self._currencies = set(Currency.objects.values_list("code", flat=True))
        for code in (record.base, record.quote):
            if code not in self._currencies:
                raise RecordRejected(f"Unknown currency {code}")
        if record.base == record.quote:
            raise RecordRejected("Base and quote currency are the same")
        if record.rate <= 0:
            raise RecordRejected(f"Non-positive rate {record.rate}")
        now = timezone.now()
        if record.observed_at > now + CLOCK_SKEW:
            raise RecordRejected(f"observed_at {record.observed_at.isoformat()} is in the future")
        if record.observed_at < now - MAX_AGE:
            raise RecordRejected(f"observed_at {record.observed_at.isoformat()} is over a day old")

    def store(self, records: Sequence[RateRecord], run: IngestionRun) -> int:
        FxMidRate.objects.bulk_create(
            [
                FxMidRate(
                    base_id=r.base,
                    quote_id=r.quote,
                    observed_at=r.observed_at,
                    rate=r.rate,
                    source=self.fx_source,
                    ingestion_run=run,
                )
                for r in records
            ],
            ignore_conflicts=True,
        )
        return len(records)

    def describe(self, record: RateRecord) -> str:
        return f"{record.base}/{record.quote} {record.rate}"
