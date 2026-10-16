from collections.abc import Sequence

import pytest

from apps.ingestion.base import Adapter, RecordRejected, TransientError
from apps.ingestion.models import IngestionRun
from apps.ingestion.registry import get_adapter, register, registered_sources
from apps.ingestion.tasks import run_adapter

pytestmark = pytest.mark.django_db

Status = IngestionRun.Status


class FakeAdapter(Adapter[list[int], int]):
    """Fetches a list of ints; rejects negatives; 'stores' into a list."""

    source = "fake"

    def __init__(self, payload=None, failures=(), store_error=None, **kwargs):
        self.sleeps: list[float] = []
        super().__init__(sleep=self.sleeps.append, **kwargs)
        self.payload = [1, 2, 3] if payload is None else payload
        self.failures = list(failures)  # exceptions raised by successive fetch calls
        self.store_error = store_error
        self.stored: list[int] = []

    def fetch(self) -> list[int]:
        if self.failures:
            raise self.failures.pop(0)
        return self.payload

    def normalize(self, raw: list[int]) -> Sequence[int]:
        return raw

    def validate(self, record: int) -> None:
        if record < 0:
            raise RecordRejected("negative")

    def store(self, records: Sequence[int], run: IngestionRun) -> int:
        if self.store_error:
            raise self.store_error
        self.stored.extend(records)
        return len(records)


def test_success_logs_run():
    adapter = FakeAdapter()
    run = adapter.run()

    assert adapter.stored == [1, 2, 3]
    run.refresh_from_db()
    assert run.source == "fake"
    assert run.status == Status.SUCCESS
    assert (run.records_fetched, run.records_stored, run.records_rejected) == (3, 3, 0)
    assert run.attempts == 1
    assert run.finished_at is not None and run.finished_at >= run.started_at
    assert run.error == ""


def test_partial_when_some_records_rejected():
    run = FakeAdapter(payload=[1, -2, 3]).run()

    assert run.status == Status.PARTIAL
    assert (run.records_stored, run.records_rejected) == (2, 1)
    assert run.details["rejections"] == [{"record": "-2", "reason": "negative"}]


def test_failed_when_every_record_rejected():
    adapter = FakeAdapter(payload=[-1, -2])
    run = adapter.run()

    assert adapter.stored == []
    assert run.status == Status.FAILED
    assert run.error == "Every record was rejected by validation."


def test_failed_when_source_returns_nothing():
    run = FakeAdapter(payload=[]).run()
    assert run.status == Status.FAILED
    assert run.error == "Source returned no records."


def test_rejection_log_is_capped():
    run = FakeAdapter(payload=[-1] * 80 + [1]).run()
    assert run.records_rejected == 80
    assert len(run.details["rejections"]) == 50


def test_transient_error_is_retried_with_backoff():
    adapter = FakeAdapter(failures=[TransientError("timeout"), TransientError("503")])
    run = adapter.run()

    assert run.status == Status.SUCCESS
    assert run.attempts == 3
    assert len(adapter.sleeps) == 2
    assert 2.0 <= adapter.sleeps[0] <= 2.2  # base 2s + up to 10% jitter
    assert 4.0 <= adapter.sleeps[1] <= 4.4


def test_gives_up_after_max_attempts():
    adapter = FakeAdapter(failures=[TransientError("timeout")] * 3)
    run = adapter.run()

    assert run.status == Status.FAILED
    assert run.attempts == 3
    assert len(adapter.sleeps) == 2  # no sleep after the final attempt
    assert run.error == "TransientError: timeout"
    assert adapter.stored == []


def test_non_transient_error_is_not_retried():
    adapter = FakeAdapter(failures=[ValueError("bad payload")])
    run = adapter.run()

    assert run.status == Status.FAILED
    assert run.attempts == 1
    assert adapter.sleeps == []
    assert run.error == "ValueError: bad payload"


def test_store_failure_marks_run_failed():
    run = FakeAdapter(store_error=RuntimeError("db down")).run()

    run.refresh_from_db()
    assert run.status == Status.FAILED
    assert run.records_stored == 0
    assert run.error == "RuntimeError: db down"


@pytest.mark.parametrize(("attempt", "low", "high"), [(1, 2, 2.2), (2, 4, 4.4), (3, 8, 8.8)])
def test_backoff_is_exponential(attempt, low, high):
    assert low <= FakeAdapter().backoff_delay(attempt) <= high


def test_backoff_is_capped():
    assert FakeAdapter().backoff_delay(20) <= FakeAdapter.backoff_max * 1.1


def test_registry_and_task():
    register(FakeAdapter)
    assert "fake" in registered_sources()
    assert get_adapter("fake") is FakeAdapter

    assert run_adapter("fake") == Status.SUCCESS
    assert IngestionRun.objects.filter(source="fake", status=Status.SUCCESS).exists()


def test_registry_rejects_duplicate_source():
    register(FakeAdapter)

    class Impostor(FakeAdapter):
        source = "fake"

    with pytest.raises(ValueError, match="already registered"):
        register(Impostor)


def test_unknown_source():
    with pytest.raises(KeyError, match="nope"):
        get_adapter("nope")
