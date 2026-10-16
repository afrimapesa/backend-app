from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.ingestion.models import IngestionRun

pytestmark = pytest.mark.django_db


def test_new_run_defaults_to_running():
    run = IngestionRun.objects.create(source="wise")
    assert run.status == IngestionRun.Status.RUNNING
    assert run.finished_at is None


def test_finished_run():
    run = IngestionRun.objects.create(source="wise")
    run.status = IngestionRun.Status.SUCCESS
    run.finished_at = timezone.now()
    run.records_fetched = run.records_stored = 15
    run.save()
    assert IngestionRun.objects.get(pk=run.pk).records_stored == 15


def test_completed_run_requires_finished_at():
    with pytest.raises(IntegrityError):
        IngestionRun.objects.create(source="wise", status=IngestionRun.Status.FAILED)


def test_finished_at_cannot_precede_start():
    run = IngestionRun.objects.create(source="wise")
    run.status = IngestionRun.Status.SUCCESS
    run.finished_at = run.started_at - timedelta(seconds=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        run.save()
