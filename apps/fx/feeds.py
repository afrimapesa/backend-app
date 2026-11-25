"""Live mid-market FX feeds (strategy doc §3.1; plan T07).

* Open Exchange Rates: USD-based rates (USD/NGN, USD/KES, ...).
* ExchangeRate-API: EUR-based rates by default (EXCHANGE_RATE_API_BASE).
* CurrencyFreaks: GBP-based rates by default (CURRENCY_FREAKS_BASE).

Each feed fetches every currency in the reference table, so adding a currency row is all it
takes to start collecting it. Pairs a feed doesn't return are skipped. Other pairs are
derived through USD at lookup time (apps.fx.services).

A feed is scheduled only when its key is set (config.settings.base). API keys are sent in
the request but never written to logs, errors or ingestion_runs.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from django.conf import settings

from apps.ingestion.base import TransientError
from apps.ingestion.registry import register
from apps.reference.models import Currency

from .ingestion import FxRateAdapter, RateRecord
from .models import FxMidRate

TIMEOUT = 20  # seconds
USER_AGENT = "AFRIMAPESA-ingestion/1.0"


class FeedError(Exception):
    """A non-retryable feed failure (bad key, plan limit, unexpected payload)."""


def get_json(url: str) -> Any:
    """GET a JSON document. Network errors, 429 and 5xx are transient; other errors are not.

    Messages never include the URL, because it carries the API key.
    """
    # Feed URLs are fixed https:// constants in this module, never user input.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        if exc.code == 429 or exc.code >= 500:
            raise TransientError(f"HTTP {exc.code}{detail}") from None
        raise FeedError(f"HTTP {exc.code}{detail}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TransientError(f"Network error: {reason}") from None
    except json.JSONDecodeError:
        raise FeedError("Response was not JSON") from None


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """The feed's own error message, if it sent one (these never echo the key)."""
    try:
        body = json.load(exc)
    except Exception:  # noqa: BLE001 - best effort only
        return ""
    for field in ("description", "message", "error-type", "error"):
        value = body.get(field) if isinstance(body, dict) else None
        if isinstance(value, str) and value:
            return f": {value[:200]}"
        if isinstance(value, dict) and value.get("message"):
            return f": {str(value['message'])[:200]}"
    return ""


def to_decimal(value: Any) -> Decimal | None:
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return rate if rate.is_finite() else None


class JsonFeed(FxRateAdapter[dict[str, Any]]):
    """Shared shape: one request returns {currency: rate} for one base currency."""

    key_setting: ClassVar[str]

    @property
    def key(self) -> str:
        """The API key; a missing key fails the run (recorded in ingestion_runs)."""
        key = str(getattr(settings, self.key_setting, "") or "")
        if not key:
            raise FeedError(f"{self.key_setting} is not set")
        return key

    @property
    def base(self) -> str:
        return "USD"

    def wanted(self) -> list[str]:
        """Every currency in the reference table except the base."""
        return sorted(Currency.objects.exclude(code=self.base).values_list("code", flat=True))

    def records(self, base: str, observed_at: datetime, rates: dict[str, Any]) -> list[RateRecord]:
        out = []
        for code in self.wanted():
            rate = to_decimal(rates.get(code)) if code in rates else None
            if rate is not None:
                out.append(RateRecord(base, code, observed_at, rate))
        return out


@register
class OpenExchangeRates(JsonFeed):
    """https://docs.openexchangerates.org/reference/latest-json (USD base on every plan)."""

    source = "openexchangerates"
    fx_source = FxMidRate.Source.OPEN_EXCHANGE_RATES
    key_setting = "OPEN_EXCHANGE_RATES_APP_ID"
    url = "https://openexchangerates.org/api/latest.json"

    def fetch(self) -> dict[str, Any]:
        query = urllib.parse.urlencode({"app_id": self.key, "symbols": ",".join(self.wanted())})
        return get_json(f"{self.url}?{query}")

    def normalize(self, raw: dict[str, Any]) -> Sequence[RateRecord]:
        if raw.get("error"):
            raise FeedError(str(raw.get("description") or raw.get("message"))[:200])
        base = raw.get("base", "USD")
        if base != self.base:
            raise FeedError(f"Expected base {self.base}, got {base}")
        observed_at = datetime.fromtimestamp(int(raw["timestamp"]), tz=UTC)
        return self.records(base, observed_at, raw.get("rates") or {})


@register
class ExchangeRateApi(JsonFeed):
    """https://www.exchangerate-api.com/docs/standard-requests (v6, any base)."""

    source = "exchangerate_api"
    fx_source = FxMidRate.Source.EXCHANGE_RATE_API
    key_setting = "EXCHANGE_RATE_API_KEY"
    url = "https://v6.exchangerate-api.com/v6"

    @property
    def base(self) -> str:
        return str(settings.EXCHANGE_RATE_API_BASE).upper()

    def fetch(self) -> dict[str, Any]:
        key = urllib.parse.quote(self.key, safe="")
        return get_json(f"{self.url}/{key}/latest/{self.base}")

    def normalize(self, raw: dict[str, Any]) -> Sequence[RateRecord]:
        if raw.get("result") != "success":
            raise FeedError(str(raw.get("error-type") or "result was not success"))
        base = raw.get("base_code")
        if base != self.base:
            raise FeedError(f"Expected base {self.base}, got {base}")
        observed_at = datetime.fromtimestamp(int(raw["time_last_update_unix"]), tz=UTC)
        return self.records(base, observed_at, raw.get("conversion_rates") or {})


@register
class CurrencyFreaks(JsonFeed):
    """https://currencyfreaks.com/documentation.html (a non-USD base needs a paid plan)."""

    source = "currencyfreaks"
    fx_source = FxMidRate.Source.CURRENCY_FREAKS
    key_setting = "CURRENCY_FREAKS_API_KEY"
    url = "https://api.currencyfreaks.com/v2.0/rates/latest"

    @property
    def base(self) -> str:
        return str(settings.CURRENCY_FREAKS_BASE).upper()

    def fetch(self) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {"apikey": self.key, "base": self.base, "symbols": ",".join(self.wanted())}
        )
        return get_json(f"{self.url}?{query}")

    def normalize(self, raw: dict[str, Any]) -> Sequence[RateRecord]:
        if raw.get("success") is False or "error" in raw:
            raise FeedError(str(raw.get("error") or raw.get("message"))[:200])
        base = raw.get("base")
        if base != self.base:
            raise FeedError(f"Expected base {self.base}, got {base}")
        return self.records(base, parse_freaks_date(str(raw["date"])), raw.get("rates") or {})


def parse_freaks_date(value: str) -> datetime:
    """CurrencyFreaks dates look like '2026-11-25 12:00:00+00'."""
    value = re.sub(r"([+-]\d{2})$", r"\1:00", value.strip())
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
