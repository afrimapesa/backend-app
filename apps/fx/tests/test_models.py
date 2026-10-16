from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection

from apps.fx.models import FxMidRate

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def make_rate(**overrides) -> FxMidRate:
    fields = {
        "base_id": "USD",
        "quote_id": "NGN",
        "observed_at": T0,
        "rate": Decimal("1532.4512"),
        "source": FxMidRate.Source.OPEN_EXCHANGE_RATES,
    } | overrides
    return FxMidRate.objects.create(**fields)


def test_is_hypertable():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'fx_mid_rates'"
        )
        assert cursor.fetchone() is not None


def test_round_trips_decimal_precision():
    make_rate(rate=Decimal("0.0006524301"))
    stored = FxMidRate.objects.get(base="USD", quote="NGN", observed_at=T0)
    assert stored.rate == Decimal("0.0006524301")
    assert stored.pk == ("USD", "NGN", T0)


def test_same_pair_and_time_is_rejected():
    make_rate()
    with pytest.raises(IntegrityError):
        make_rate(rate=Decimal("1533"))


def test_same_pair_different_time_is_allowed():
    make_rate()
    make_rate(observed_at=T0.replace(minute=5))
    assert FxMidRate.objects.count() == 2


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("-1")])
def test_rate_must_be_positive(rate):
    with pytest.raises(IntegrityError):
        make_rate(rate=rate)


def test_base_and_quote_must_differ():
    with pytest.raises(IntegrityError):
        make_rate(quote_id="USD")
