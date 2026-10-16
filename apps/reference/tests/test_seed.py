import pytest
from django.db import IntegrityError
from django.urls import reverse

from apps.reference.models import Corridor, Country, Currency, Provider

pytestmark = pytest.mark.django_db


def test_seeds_eighteen_corridors():
    assert Corridor.objects.count() == 18
    assert set(Country.objects.filter(is_sending=True).values_list("code", flat=True)) == {
        "US",
        "GB",
        "EU",
    }
    assert Country.objects.filter(is_receiving=True).count() == 6


def test_corridor_currencies_match_country_currencies():
    for corridor in Corridor.objects.select_related("send_country", "receive_country"):
        assert corridor.send_currency_id == corridor.send_country.currency_id
        assert corridor.receive_currency_id == corridor.receive_country.currency_id


def test_corridor_code():
    corridor = Corridor.objects.get(send_country="GB", receive_country="NG")
    assert corridor.code == "GB-GBP-NG-NGN"


@pytest.mark.parametrize(
    ("slug", "expected_count"),
    [
        ("wise", 15),  # 3 senders x 5 receivers (no TZ)
        ("remitly", 18),
        ("chipper-cash", 8),  # US, UK x NG, GH, KE, ZA
        ("revolut", 10),  # UK, EU x 5
        ("opay", 6),
    ],
)
def test_provider_corridor_coverage(slug, expected_count):
    assert Provider.objects.get(slug=slug).corridors.count() == expected_count


def test_wise_refreshes_every_five_minutes():
    assert Provider.objects.get(slug="wise").update_interval.total_seconds() == 300


def test_corridor_is_unique():
    with pytest.raises(IntegrityError):
        Corridor.objects.create(
            send_country_id="GB",
            send_currency_id="GBP",
            receive_country_id="NG",
            receive_currency_id="NGN",
        )


def test_corridor_rejects_same_country():
    with pytest.raises(IntegrityError):
        Corridor.objects.create(
            send_country_id="NG",
            send_currency_id="NGN",
            receive_country_id="NG",
            receive_currency_id="NGN",
        )


def test_currency_list_endpoint(client):
    response = client.get(reverse("currency-list"))
    assert response.status_code == 200
    assert len(response.json()) == Currency.objects.count() == 9


@pytest.mark.parametrize(("role", "expected"), [("sending", 3), ("receiving", 6), (None, 9)])
def test_country_list_role_filter(client, role, expected):
    params = {"role": role} if role else {}
    response = client.get(reverse("country-list"), params)
    assert response.status_code == 200
    assert len(response.json()) == expected


def test_corridor_list_endpoint(client):
    response = client.get(reverse("corridor-list"))
    assert response.status_code == 200
    assert "GB-GBP-NG-NGN" in {c["code"] for c in response.json()}


def test_provider_detail_endpoint(client):
    response = client.get(reverse("provider-detail", args=["wise"]))
    assert response.status_code == 200
    body = response.json()
    assert body["integration_method"] == "public_api"
    assert "US-USD-TZ-TZS" not in body["corridors"]
    assert "US-USD-NG-NGN" in body["corridors"]
