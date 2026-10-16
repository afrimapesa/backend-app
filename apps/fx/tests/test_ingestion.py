from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.utils import timezone

from apps.fx.ingestion import FxRateAdapter, RateRecord
from apps.fx.models import FxMidRate
from apps.fx.services import latest_mid_rate
from apps.ingestion.models import IngestionRun

pytestmark = pytest.mark.django_db


def add_rate(base, quote, rate, at):
    FxMidRate.objects.create(
        base_id=base, quote_id=quote, rate=D(rate), observed_at=at, source="manual"
    )


class TestLatestMidRate:
    def test_direct(self):
        now = timezone.now()
        add_rate("GBP", "NGN", "2030", now - timedelta(minutes=10))
        add_rate("GBP", "NGN", "2040", now - timedelta(minutes=2))
        assert latest_mid_rate("GBP", "NGN", at=now) == D("2040")

    def test_ignores_rates_after_at(self):
        now = timezone.now()
        add_rate("GBP", "NGN", "2030", now - timedelta(minutes=10))
        add_rate("GBP", "NGN", "2040", now + timedelta(minutes=1))
        assert latest_mid_rate("GBP", "NGN", at=now) == D("2030")

    def test_cross_rate_through_usd(self):
        now = timezone.now()
        add_rate("USD", "NGN", "1530", now)
        add_rate("USD", "KES", "129.2", now)
        # NGN/KES = 1/(USD/NGN) x (USD/KES)
        assert latest_mid_rate("NGN", "KES", at=now) == D("129.2") / D("1530")

    def test_stale_rate_is_ignored(self):
        now = timezone.now()
        add_rate("GBP", "NGN", "2040", now - timedelta(minutes=31))
        assert latest_mid_rate("GBP", "NGN", at=now) is None

    def test_missing_leg_returns_none(self):
        now = timezone.now()
        add_rate("USD", "NGN", "1530", now)
        assert latest_mid_rate("NGN", "KES", at=now) is None
        assert latest_mid_rate("USD", "KES", at=now) is None

    def test_same_currency(self):
        assert latest_mid_rate("NGN", "NGN", at=timezone.now()) == 1


class FakeFeed(FxRateAdapter[list[RateRecord]]):
    source = "fake_fx"
    fx_source = FxMidRate.Source.OPEN_EXCHANGE_RATES

    def __init__(self, records):
        super().__init__(sleep=lambda _: None)
        self.records = records

    def fetch(self):
        return self.records

    def normalize(self, raw) -> Sequence[RateRecord]:
        return raw


def test_fx_adapter_stores_valid_and_rejects_invalid():
    now = timezone.now()
    run = FakeFeed(
        [
            RateRecord("USD", "NGN", now, D("1530.25")),
            RateRecord("USD", "KES", now, D("129.2")),
            RateRecord("USD", "XYZ", now, D("1")),  # unknown currency
            RateRecord("USD", "USD", now, D("1")),  # same currency
            RateRecord("USD", "GHS", now, D("0")),  # non-positive
            RateRecord("USD", "ZAR", now + timedelta(hours=1), D("17.7")),  # future
            RateRecord("USD", "EGP", now - timedelta(days=2), D("48.6")),  # too old
        ]
    ).run()

    assert run.status == IngestionRun.Status.PARTIAL
    assert (run.records_stored, run.records_rejected) == (2, 5)
    stored = FxMidRate.objects.get(base="USD", quote="NGN")
    assert stored.rate == D("1530.25")
    assert stored.source == "openexchangerates"
    assert stored.ingestion_run_id == run.pk


def test_fx_adapter_redelivery_is_idempotent():
    now = timezone.now()
    records = [RateRecord("USD", "NGN", now, D("1530.25"))]
    FakeFeed(records).run()
    run = FakeFeed(records).run()

    assert run.status == IngestionRun.Status.SUCCESS
    assert FxMidRate.objects.filter(base="USD", quote="NGN").count() == 1
