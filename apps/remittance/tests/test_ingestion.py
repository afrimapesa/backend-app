from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.utils import timezone

from apps.fx.models import FxMidRate
from apps.ingestion.models import IngestionRun
from apps.remittance.ingestion import ProviderQuoteAdapter, QuoteRecord
from apps.remittance.models import ProviderQuote

pytestmark = pytest.mark.django_db

Status = IngestionRun.Status


class FakeWise(ProviderQuoteAdapter[list[QuoteRecord]]):
    source = "fake_wise"
    provider_slug = "wise"

    def __init__(self, records):
        super().__init__(sleep=lambda _: None)
        self.records = records

    def fetch(self):
        return self.records

    def normalize(self, raw) -> Sequence[QuoteRecord]:
        return raw


@pytest.fixture
def now():
    t = timezone.now()
    FxMidRate.objects.create(
        base_id="GBP",
        quote_id="NGN",
        rate=D("2040"),
        observed_at=t - timedelta(minutes=3),
        source="manual",
    )
    FxMidRate.objects.create(
        base_id="GBP",
        quote_id="KES",
        rate=D("172.3"),
        observed_at=t - timedelta(minutes=3),
        source="manual",
    )
    return t


def quote(now, send="GB", receive="NG", rate="2035.10", **kw):
    return QuoteRecord(
        send_country=send, receive_country=receive, observed_at=now, fx_rate=D(rate), **kw
    )


def test_stores_valid_quotes_linked_to_run(now):
    run = FakeWise(
        [
            quote(
                now, fee_flat=D("0.79"), fee_pct=D("0.0045"), transfer_time=timedelta(minutes=30)
            ),
            quote(now, receive="KE", rate="171.9"),
        ]
    ).run()

    assert run.status == Status.SUCCESS
    assert run.provider.slug == "wise"
    assert run.records_stored == 2
    stored = ProviderQuote.objects.get(corridor__receive_country="NG")
    assert stored.provider.slug == "wise"
    assert stored.fee_pct == D("0.0045")
    assert stored.ingestion_run_id == run.pk
    assert stored.source == ProviderQuote.Source.ADAPTER


@pytest.mark.parametrize(
    ("record_kwargs", "reason"),
    [
        ({"rate": "1500"}, "below mid-market"),  # 26% under mid: parsing error
        ({"rate": "2200"}, "above mid-market"),
        ({"receive": "TZ"}, "does not serve GB->TZ"),  # Wise has no Tanzania corridor
        ({"receive": "GH"}, "No fresh mid-market rate"),  # no GBP/GHS or USD legs stored
        ({"fee_flat": D("-1")}, "Negative flat fee"),
        ({"fee_pct": D("1.5")}, "not a fraction"),
        ({"min_amount": D("100"), "max_amount": D("10")}, "min_amount"),
    ],
)
def test_rejects_bad_quotes_with_reason(now, record_kwargs, reason):
    run = FakeWise([quote(now), quote(now, **record_kwargs)]).run()

    assert run.status == Status.PARTIAL
    assert run.records_rejected == 1
    assert reason in run.details["rejections"][0]["reason"]
    assert ProviderQuote.objects.count() == 1


def test_rejects_future_timestamp(now):
    run = FakeWise([quote(now + timedelta(hours=1))]).run()
    assert run.status == Status.FAILED
    assert "in the future" in run.details["rejections"][0]["reason"]


def test_mid_rate_is_checked_as_of_quote_time(now):
    # The only mid rate is 3 min old; a quote observed 40 min ago predates it -> no reference.
    run = FakeWise([quote(now - timedelta(minutes=40))]).run()
    assert run.status == Status.FAILED
    assert "No fresh mid-market rate" in run.details["rejections"][0]["reason"]


def test_redelivered_quote_is_idempotent(now):
    FakeWise([quote(now)]).run()
    run = FakeWise([quote(now)]).run()

    assert run.status == Status.SUCCESS
    assert ProviderQuote.objects.count() == 1
