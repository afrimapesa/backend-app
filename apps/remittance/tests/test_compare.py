from datetime import timedelta
from decimal import Decimal as D
from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.fx.models import FxMidRate
from apps.reference.models import Corridor, Provider
from apps.remittance import compare
from apps.remittance.models import ProviderQuote

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def now():
    return timezone.now()


@pytest.fixture
def gb_ng(now):
    # GBP/NGN mid = 1530 / 0.75 = 2040, derived through USD like the real feeds.
    for code, rate in [("GBP", "0.75"), ("NGN", "1530")]:
        FxMidRate.objects.create(
            base_id="USD", quote_id=code, rate=D(rate), observed_at=now, source="manual"
        )
    return Corridor.objects.select_related("send_currency", "receive_currency").get(
        send_country="GB", receive_country="NG"
    )


def add_quote(corridor, slug, rate, observed_at, **kw):
    return ProviderQuote.objects.create(
        provider=Provider.objects.get(slug=slug),
        corridor=corridor,
        observed_at=observed_at,
        fx_rate=D(rate),
        **kw,
    )


class TestCompareService:
    def test_ranks_top_five_by_payout(self, gb_ng, now):
        for slug, rate in [
            ("wise", "2030"),
            ("remitly", "2000"),
            ("lemfi", "2035"),
            ("nala", "2020"),
            ("sendwave", "2010"),
            ("xe", "1990"),
        ]:
            add_quote(gb_ng, slug, rate, now - timedelta(minutes=1))

        result = compare.compare(gb_ng, D("200"), now=now)

        assert [r.provider for r in result.results] == [
            "lemfi",
            "wise",
            "nala",
            "sendwave",
            "remitly",
        ]
        assert [r.rank for r in result.results] == [1, 2, 3, 4, 5]
        assert result.snapshot.mid.rate == D("2040")
        assert result.mid_payout == D("408000.00")
        assert result.snapshot.providers_on_route == 15
        assert result.sample is False

    def test_uses_latest_quote_per_provider(self, gb_ng, now):
        add_quote(gb_ng, "wise", "1900", now - timedelta(minutes=30))
        add_quote(gb_ng, "wise", "2030", now - timedelta(minutes=1))
        [only] = compare.compare(gb_ng, D("100"), now=now).results
        assert only.fx_rate == D("2030")

    def test_stale_quotes_flagged_and_ranked_after_fresh(self, gb_ng, now):
        # Wise refreshes every 5 min: 20 min old is stale (> 2x interval), even if cheaper.
        add_quote(gb_ng, "wise", "2039", now - timedelta(minutes=20))
        add_quote(gb_ng, "remitly", "2000", now - timedelta(minutes=1))
        results = compare.compare(gb_ng, D("100"), now=now).results
        assert [(r.provider, r.is_stale) for r in results] == [("remitly", False), ("wise", True)]

    def test_excludes_inactive_old_and_future_quotes(self, gb_ng, now):
        Provider.objects.filter(slug="xe").update(is_active=False)
        add_quote(gb_ng, "xe", "2039", now - timedelta(minutes=1))
        add_quote(gb_ng, "wise", "2039", now - timedelta(hours=25))
        add_quote(gb_ng, "nala", "2039", now + timedelta(minutes=5))
        add_quote(gb_ng, "remitly", "2000", now - timedelta(minutes=1))
        results = compare.compare(gb_ng, D("100"), now=now).results
        assert [r.provider for r in results] == ["remitly"]

    def test_no_mid_rate_means_no_results(self, now):
        corridor = Corridor.objects.get(send_country="GB", receive_country="KE")
        add_quote(corridor, "wise", "170", now - timedelta(minutes=1))
        result = compare.compare(corridor, D("100"), now=now)
        assert result.snapshot.mid is None
        assert result.results == []
        assert result.mid_payout is None

    def test_sample_flag(self, gb_ng, now):
        add_quote(gb_ng, "wise", "2030", now - timedelta(minutes=1), source="sample")
        assert compare.compare(gb_ng, D("100"), now=now).sample is True

    def test_snapshot_is_cached(self, gb_ng, now, django_assert_num_queries):
        add_quote(gb_ng, "wise", "2030", now - timedelta(minutes=1))
        compare.compare(gb_ng, D("100"), now=now)
        with django_assert_num_queries(0):
            again = compare.compare(gb_ng, D("250"), now=now)
        assert again.results[0].amount == D("250")

    def test_invalidate_drops_snapshot(self, gb_ng, now):
        add_quote(gb_ng, "wise", "2030", now - timedelta(minutes=1))
        compare.compare(gb_ng, D("100"), now=now)
        add_quote(gb_ng, "remitly", "2035", now - timedelta(minutes=1))
        assert len(compare.compare(gb_ng, D("100"), now=now).results) == 1  # cached
        compare.invalidate([gb_ng.pk])
        assert len(compare.compare(gb_ng, D("100"), now=now).results) == 2


class TestCompareEndpoint:
    def test_response(self, client, gb_ng, now):
        add_quote(
            gb_ng,
            "wise",
            "2030",
            now - timedelta(minutes=1),
            fee_flat=D("0.79"),
            transfer_time=timedelta(minutes=30),
        )
        response = client.get(
            reverse("remittance-compare"), {"send": "gb", "receive": "ng", "amount": "200"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["corridor"] == "GB-GBP-NG-NGN"
        assert body["as_of"]
        assert D(body["mid_payout"]) == D("408000.00")
        assert body["sample"] is False
        [row] = body["results"]
        assert row["provider"] == {"slug": "wise", "name": "Wise", "website": "https://wise.com"}
        assert D(row["transfer_fee"]) == D("0.79")
        # total cost = 200 - payout / mid; margin is the part not explained by the fee
        assert D(row["margin_cost"]) == D(row["total_cost"]) - D(row["transfer_fee"])
        assert row["transfer_time_minutes"] == 30
        assert row["is_stale"] is False

    @pytest.mark.parametrize(
        ("params", "status"),
        [
            ({"send": "GB", "receive": "XX", "amount": "200"}, 404),
            ({"send": "NG", "receive": "GB", "amount": "200"}, 404),
            ({"send": "GB", "receive": "NG", "amount": "0"}, 400),
            ({"send": "GB", "receive": "NG", "amount": "2000000"}, 400),
            ({"send": "GB", "receive": "NG", "amount": "abc"}, 400),
            ({"send": "GB", "receive": "NG"}, 400),
        ],
    )
    def test_bad_requests(self, client, params, status):
        assert client.get(reverse("remittance-compare"), params).status_code == status


def test_adapter_store_invalidates_cache(gb_ng, now, django_capture_on_commit_callbacks):
    from apps.remittance.tests.test_ingestion import FakeWise, quote

    # The quote is validated against the mid rate as of its own timestamp, so the
    # reference rate must predate it.
    FxMidRate.objects.create(
        base_id="GBP",
        quote_id="NGN",
        rate=D("2040"),
        observed_at=now - timedelta(minutes=5),
        source="manual",
    )
    compare.compare(gb_ng, D("100"), now=now)  # caches an empty snapshot
    with django_capture_on_commit_callbacks(execute=True):
        FakeWise([quote(now - timedelta(minutes=1))]).run()
    assert len(compare.compare(gb_ng, D("100"), now=timezone.now()).results) == 1


class TestSeedSampleQuotes:
    def test_seeds_labelled_sample_data(self):
        call_command("seed_sample_quotes", stdout=StringIO())
        assert ProviderQuote.objects.exclude(source="sample").count() == 0
        assert ProviderQuote.objects.filter(source="sample").count() > 100
        # 89 days of history + today's rate for each of 8 USD legs
        assert FxMidRate.objects.filter(source="sample").count() == 8 * 90

        corridor = Corridor.objects.select_related("send_currency", "receive_currency").get(
            send_country="GB", receive_country="NG"
        )
        result = compare.compare(corridor, D("200"), now=timezone.now())
        assert len(result.results) == 5
        assert result.sample is True

    def test_refresh_adds_rates_without_new_history(self):
        call_command("seed_sample_quotes", stdout=StringIO())
        call_command("seed_sample_quotes", stdout=StringIO())
        assert FxMidRate.objects.filter(source="sample").count() == 8 * 91

    def test_clear_removes_only_sample_data(self, gb_ng, now):
        call_command("seed_sample_quotes", stdout=StringIO())
        call_command("seed_sample_quotes", "--clear", stdout=StringIO())
        assert ProviderQuote.objects.filter(source="sample").count() == 0
        assert FxMidRate.objects.filter(source="sample").count() == 0
        assert FxMidRate.objects.filter(source="manual").count() == 2  # gb_ng fixture rows
