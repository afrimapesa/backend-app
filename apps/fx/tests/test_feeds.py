import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.fx import feeds
from apps.fx.models import FxMidRate
from apps.ingestion.base import TransientError
from apps.ingestion.models import IngestionRun
from apps.ingestion.registry import registered_sources
from apps.remittance.models import ProviderQuote

pytestmark = pytest.mark.django_db

KEY = "secret-key-123"


@pytest.fixture
def keys(settings):
    settings.OPEN_EXCHANGE_RATES_APP_ID = KEY
    settings.EXCHANGE_RATE_API_KEY = KEY
    settings.CURRENCY_FREAKS_API_KEY = KEY
    settings.EXCHANGE_RATE_API_BASE = "EUR"
    settings.CURRENCY_FREAKS_BASE = "GBP"


@pytest.fixture
def served(monkeypatch):
    """Serve a canned payload instead of calling the network; remember the URL asked for."""
    calls = []

    def serve(payload):
        def fake_get_json(url):
            calls.append(url)
            return payload

        monkeypatch.setattr(feeds, "get_json", fake_get_json)
        return calls

    return serve


def run(cls):
    return cls(sleep=lambda _: None).run()


def test_feeds_are_registered():
    assert {"openexchangerates", "exchangerate_api", "currencyfreaks"} <= set(registered_sources())


def test_open_exchange_rates_stores_usd_rates(keys, served):
    now = timezone.now().replace(microsecond=0)
    calls = served(
        {
            "timestamp": int(now.timestamp()),
            "base": "USD",
            "rates": {"NGN": 1452.31, "KES": 129.2, "XOF": 565.1, "ABC": 3, "GHS": "n/a"},
        }
    )
    result = run(feeds.OpenExchangeRates)

    assert result.status == IngestionRun.Status.SUCCESS
    stored = dict(
        FxMidRate.objects.filter(source="openexchangerates").values_list("quote_id", "rate")
    )
    # Unknown codes (ABC) and unparseable rates (GHS) are skipped; new African currencies kept.
    assert stored == {"NGN": D("1452.31"), "KES": D("129.2"), "XOF": D("565.1")}
    assert FxMidRate.objects.filter(source="openexchangerates").first().observed_at == now
    assert "symbols=" in calls[0] and "NGN" in calls[0]


def test_exchangerate_api_uses_configured_base(keys, served):
    now = timezone.now().replace(microsecond=0)
    calls = served(
        {
            "result": "success",
            "base_code": "EUR",
            "time_last_update_unix": int(now.timestamp()),
            "conversion_rates": {"NGN": 1689.5, "ZAR": 20.4, "EUR": 1},
        }
    )
    assert run(feeds.ExchangeRateApi).status == IngestionRun.Status.SUCCESS
    rows = FxMidRate.objects.filter(source="exchangerate_api")
    assert set(rows.values_list("base_id", "quote_id")) == {("EUR", "NGN"), ("EUR", "ZAR")}
    assert calls[0].endswith("/latest/EUR")


def test_exchangerate_api_error_result_fails_the_run(keys, served):
    served({"result": "error", "error-type": "invalid-key"})
    result = run(feeds.ExchangeRateApi)
    assert result.status == IngestionRun.Status.FAILED
    assert "invalid-key" in result.error
    assert KEY not in result.error


def test_currencyfreaks_parses_string_rates_and_date(keys, served):
    stamp = (timezone.now() - timedelta(minutes=5)).replace(second=0, microsecond=0)
    served(
        {
            "date": stamp.strftime("%Y-%m-%d %H:%M:%S+00"),
            "base": "GBP",
            "rates": {"NGN": "1934.12", "GHS": "19.6"},
        }
    )
    assert run(feeds.CurrencyFreaks).status == IngestionRun.Status.SUCCESS
    row = FxMidRate.objects.get(source="currencyfreaks", quote_id="NGN")
    assert (row.base_id, row.rate, row.observed_at) == ("GBP", D("1934.12"), stamp)


def test_wrong_base_fails_the_run(keys, served):
    served({"date": "2026-11-25 12:00:00+00", "base": "USD", "rates": {"NGN": "1"}})
    result = run(feeds.CurrencyFreaks)
    assert result.status == IngestionRun.Status.FAILED
    assert "Expected base GBP" in result.error


def test_missing_key_fails_the_run_without_calling_out(settings, served):
    settings.OPEN_EXCHANGE_RATES_APP_ID = ""
    calls = served({})
    result = run(feeds.OpenExchangeRates)
    assert result.status == IngestionRun.Status.FAILED
    assert "OPEN_EXCHANGE_RATES_APP_ID is not set" in result.error
    assert calls == []


def test_parse_freaks_date():
    assert feeds.parse_freaks_date("2026-11-25 12:43:00+00") == datetime(
        2026, 11, 25, 12, 43, tzinfo=UTC
    )


class TestGetJson:
    def _raise(self, monkeypatch, exc):
        def boom(*args, **kwargs):
            raise exc

        monkeypatch.setattr(feeds.urllib.request, "urlopen", boom)

    def _http_error(self, code, body):
        url = f"https://example.test/latest?app_id={KEY}"
        return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(json.dumps(body).encode()))

    def test_server_errors_and_rate_limits_are_transient(self, monkeypatch):
        for code in (429, 503):
            self._raise(monkeypatch, self._http_error(code, {}))
            with pytest.raises(TransientError):
                feeds.get_json(f"https://example.test/?app_id={KEY}")

    def test_client_errors_are_permanent_and_never_leak_the_key(self, monkeypatch):
        self._raise(monkeypatch, self._http_error(401, {"message": "invalid_app_id"}))
        with pytest.raises(feeds.FeedError) as excinfo:
            feeds.get_json(f"https://example.test/?app_id={KEY}")
        assert "invalid_app_id" in str(excinfo.value)
        assert KEY not in str(excinfo.value)

    def test_network_errors_are_transient(self, monkeypatch):
        self._raise(monkeypatch, urllib.error.URLError("timed out"))
        with pytest.raises(TransientError):
            feeds.get_json("https://example.test/")


def test_seeder_quotes_only_prices_on_live_rates():
    now = timezone.now()
    for code, rate in [("NGN", "1450"), ("GBP", "0.79")]:
        FxMidRate.objects.create(
            base_id="USD", quote_id=code, rate=D(rate), observed_at=now, source="openexchangerates"
        )
    call_command("seed_sample_quotes", "--quotes-only", stdout=StringIO())

    assert not FxMidRate.objects.filter(source="sample").exists()
    quotes = ProviderQuote.objects.filter(source="sample")
    # Only corridors with live rates on both legs (USD/GBP -> NGN) get quotes.
    pairs = set(quotes.values_list("corridor__send_currency_id", "corridor__receive_currency_id"))
    assert pairs == {("USD", "NGN"), ("GBP", "NGN")}
    us_ng = quotes.filter(
        corridor__send_currency_id="USD", corridor__receive_currency_id="NGN"
    ).first()
    assert D("1400") < us_ng.fx_rate <= D("1450")


def test_seeder_clear_rates_keeps_live_rates():
    now = timezone.now()
    FxMidRate.objects.create(
        base_id="USD", quote_id="NGN", rate=D("1450"), observed_at=now, source="openexchangerates"
    )
    call_command("seed_sample_quotes", stdout=StringIO())
    call_command("seed_sample_quotes", "--clear-rates", stdout=StringIO())
    assert not FxMidRate.objects.filter(source="sample").exists()
    assert FxMidRate.objects.filter(source="openexchangerates").count() == 1
