from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection

from apps.reference.models import Corridor, Provider
from apps.remittance import engine
from apps.remittance.models import ProviderQuote

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def wise():
    return Provider.objects.get(slug="wise")


@pytest.fixture
def gb_ng():
    return Corridor.objects.get(send_country="GB", receive_country="NG")


def make_quote(provider, corridor, **overrides) -> ProviderQuote:
    fields = {
        "provider": provider,
        "corridor": corridor,
        "observed_at": T0,
        "fx_rate": Decimal("1985.20"),
        "fee_flat": Decimal("0.79"),
        "fee_pct": Decimal("0.0045"),
    } | overrides
    return ProviderQuote.objects.create(**fields)


def test_is_hypertable():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'provider_quotes'"
        )
        assert cursor.fetchone() is not None


def test_duplicate_observation_rejected(wise, gb_ng):
    make_quote(wise, gb_ng)
    with pytest.raises(IntegrityError):
        make_quote(wise, gb_ng, fx_rate=Decimal("1990"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"fx_rate": Decimal("0")},
        {"fee_flat": Decimal("-0.01")},
        {"fee_pct": Decimal("1")},
        {"fee_pct": Decimal("-0.001")},
        {"min_amount": Decimal("100"), "max_amount": Decimal("50")},
    ],
)
def test_check_constraints(wise, gb_ng, overrides):
    with pytest.raises(IntegrityError):
        make_quote(wise, gb_ng, **overrides)


def test_latest_quotes_per_corridor(wise, gb_ng):
    remitly = Provider.objects.get(slug="remitly")
    make_quote(wise, gb_ng, observed_at=T0 - timedelta(minutes=5), fx_rate=Decimal("1980"))
    make_quote(wise, gb_ng)
    make_quote(remitly, gb_ng, fx_rate=Decimal("1962"))

    latest = (
        ProviderQuote.objects.filter(corridor=gb_ng)
        .order_by("provider_id", "-observed_at")
        .distinct("provider_id")
    )
    assert {(q.provider.slug, q.fx_rate) for q in latest} == {
        ("wise", Decimal("1985.20")),
        ("remitly", Decimal("1962")),
    }


def test_to_engine_round_trip(wise, gb_ng):
    quote = make_quote(
        wise,
        gb_ng,
        min_amount=Decimal("1"),
        max_amount=Decimal("1000000"),
        transfer_time=timedelta(minutes=30),
    )
    engine_quote = ProviderQuote.objects.get(pk=quote.pk).to_engine()

    assert engine_quote.provider == "wise"
    assert engine_quote.update_interval == timedelta(minutes=5)
    result = engine.calculate(engine_quote, Decimal("200"), Decimal("2000"), T0)
    assert result is not None
    assert result.transfer_fee == Decimal("1.69")  # 0.79 + 200 * 0.0045
    assert result.net_payout == Decimal("393685.01")
