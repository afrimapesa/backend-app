from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.fx.models import FxMidRate
from apps.fx.movers import movers

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def add(quote, rate, day, source="manual"):
    FxMidRate.objects.create(
        base_id="USD",
        quote_id=quote,
        rate=D(rate),
        observed_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
        source=source,
    )


def test_changes_per_receiving_currency(django_assert_num_queries):
    add("NGN", "1500", TODAY - timedelta(days=2))
    add("NGN", "1500", TODAY - timedelta(days=1))
    add("NGN", "1530", TODAY)
    add("KES", "130", TODAY, source="sample")

    result = {m.currency: m for m in movers("USD", days=7, today=TODAY)}

    ngn = result["NGN"]
    assert ngn.rate == D("1530") and ngn.country == "Nigeria"
    assert ngn.change_1d == D("0.02") and ngn.change_period == D("0.02")
    assert len(ngn.points) == 3 and ngn.sample is False
    kes = result["KES"]
    assert kes.change_1d is None and kes.sample is True
    assert "GHS" not in result  # no data, not listed
    assert "GBP" not in result  # sending markets are not movers

    with django_assert_num_queries(0):
        movers("USD", days=7, today=TODAY)


def test_movers_endpoint(client):
    add("NGN", "1500", timezone.now().date() - timedelta(days=1))
    add("NGN", "1515", timezone.now().date())
    body = client.get(reverse("fx-movers"), {"days": 7}).json()
    assert body["base"] == "USD" and body["days"] == 7
    (ngn,) = body["movers"]
    assert ngn["currency"] == "NGN" and D(ngn["change_1d"]) == D("0.01")
    assert len(ngn["points"]) == 2


def test_movers_rejects_unknown_base(client):
    assert client.get(reverse("fx-movers"), {"base": "XXX"}).status_code == 400
