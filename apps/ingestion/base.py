"""Base ingestion adapter: fetch -> normalize -> validate -> store, with retries and run logging.

Every data source (FX feed, provider API, scraper) subclasses :class:`Adapter` and
implements the four steps. :meth:`Adapter.run` provides the shared behaviour:

* each run is recorded in ``ingestion_runs`` whatever happens (T09);
* only ``fetch`` is retried, and only on :class:`TransientError` (network blips, 5xx,
  rate limits), with exponential backoff and jitter;
* invalid records are rejected individually with a reason, not the whole batch;
* valid records are stored in one transaction, so a failed store leaves nothing behind.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar

from django.db import transaction
from django.utils import timezone

from apps.reference.models import Provider

from .models import IngestionRun

logger = logging.getLogger(__name__)

MAX_LOGGED_REJECTIONS = 50
MAX_ERROR_LENGTH = 2000


class TransientError(Exception):
    """A failure worth retrying: timeouts, connection errors, HTTP 429/5xx."""


class RecordRejected(Exception):  # noqa: N818 - reads naturally at raise sites
    """Raised by ``validate`` to reject one record. The message is the logged reason."""


@dataclass(frozen=True)
class Rejection:
    record: str
    reason: str


class Adapter[RawT, RecordT](ABC):
    source: ClassVar[str]
    provider_slug: ClassVar[str | None] = None

    max_attempts: ClassVar[int] = 3
    backoff_base: ClassVar[float] = 2.0  # seconds; doubles each attempt
    backoff_max: ClassVar[float] = 60.0

    def __init__(self, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._sleep = sleep

    # --- the four steps --------------------------------------------------------------

    @abstractmethod
    def fetch(self) -> RawT:
        """Get raw data from the source. Raise TransientError for retryable failures."""

    @abstractmethod
    def normalize(self, raw: RawT) -> Sequence[RecordT]:
        """Turn the raw payload into typed records."""

    def validate(self, record: RecordT) -> None:  # noqa: B027 - optional hook
        """Raise RecordRejected if the record must not be stored."""

    @abstractmethod
    def store(self, records: Sequence[RecordT], run: IngestionRun) -> int:
        """Persist valid records; return how many were written."""

    # --- orchestration ---------------------------------------------------------------

    def run(self) -> IngestionRun:
        run = IngestionRun.objects.create(source=self.source, provider=self._provider())
        try:
            raw = self._fetch_with_retries(run)
            records = list(self.normalize(raw))
            run.records_fetched = len(records)

            valid, rejections = self._validate_all(records)
            run.records_rejected = len(rejections)
            if rejections:
                run.details["rejections"] = [
                    {"record": r.record, "reason": r.reason}
                    for r in rejections[:MAX_LOGGED_REJECTIONS]
                ]

            if valid:
                with transaction.atomic():
                    run.records_stored = self.store(valid, run)

            run.status = self._status(run)
            if run.status == IngestionRun.Status.FAILED and not run.error:
                run.error = (
                    "Source returned no records."
                    if not records
                    else "Every record was rejected by validation."
                )
        except Exception as exc:
            logger.exception("Ingestion run failed: %s", self.source)
            run.status = IngestionRun.Status.FAILED
            run.records_stored = 0
            run.error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
        finally:
            run.finished_at = timezone.now()
            run.save()
        logger.info(
            "Ingestion %s: %s (fetched=%d stored=%d rejected=%d attempts=%d)",
            self.source,
            run.status,
            run.records_fetched,
            run.records_stored,
            run.records_rejected,
            run.attempts,
        )
        return run

    def backoff_delay(self, attempt: int) -> float:
        """Delay before retry number ``attempt`` (1-based): exponential, capped, with jitter."""
        delay = min(self.backoff_max, self.backoff_base * 2 ** (attempt - 1))
        return delay + random.uniform(0, delay * 0.1)  # noqa: S311 - not cryptographic

    def _fetch_with_retries(self, run: IngestionRun) -> RawT:
        for attempt in range(1, self.max_attempts + 1):
            run.attempts = attempt
            try:
                return self.fetch()
            except TransientError as exc:
                if attempt == self.max_attempts:
                    raise
                delay = self.backoff_delay(attempt)
                logger.warning(
                    "%s fetch attempt %d/%d failed (%s); retrying in %.1fs",
                    self.source,
                    attempt,
                    self.max_attempts,
                    exc,
                    delay,
                )
                self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _validate_all(self, records: list[RecordT]) -> tuple[list[RecordT], list[Rejection]]:
        valid: list[RecordT] = []
        rejections: list[Rejection] = []
        for record in records:
            try:
                self.validate(record)
            except RecordRejected as exc:
                rejections.append(Rejection(record=self.describe(record), reason=str(exc)))
            else:
                valid.append(record)
        return valid, rejections

    def describe(self, record: RecordT) -> str:
        """Short human-readable label for a record, used in rejection logs."""
        return str(record)[:200]

    def _provider(self) -> Provider | None:
        if self.provider_slug is None:
            return None
        return Provider.objects.get(slug=self.provider_slug)

    @staticmethod
    def _status(run: IngestionRun) -> IngestionRun.Status:
        if run.records_stored == 0:
            return IngestionRun.Status.FAILED
        if run.records_rejected:
            return IngestionRun.Status.PARTIAL
        return IngestionRun.Status.SUCCESS
