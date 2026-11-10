"""List the main euro-area countries as senders instead of "European Union".

Each one is priced with the EU corridors (pricing_market=EU): providers quote euro transfers
the same across the euro area, so no corridors or quotes are duplicated. The EU row stays
active because the corridors and quotes hang off it; it just leaves the sender list.
A country can be given its own corridors later by clearing its pricing_market.
"""

from django.db import migrations

EURO_SENDERS = [
    ("AT", "Austria"),
    ("BE", "Belgium"),
    ("FI", "Finland"),
    ("FR", "France"),
    ("DE", "Germany"),
    ("IE", "Ireland"),
    ("IT", "Italy"),
    ("NL", "Netherlands"),
    ("PT", "Portugal"),
    ("ES", "Spain"),
]


def add(apps, schema_editor):
    Country = apps.get_model("reference", "Country")
    for code, name in EURO_SENDERS:
        Country.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "kind": "country",
                "currency_id": "EUR",
                "is_sending": True,
                "pricing_market_id": "EU",
                "is_active": True,
            },
        )
    Country.objects.filter(code="EU").update(is_sending=False)


def remove(apps, schema_editor):
    Country = apps.get_model("reference", "Country")
    Country.objects.filter(code="EU").update(is_sending=True)
    Country.objects.filter(code__in=[c for c, _ in EURO_SENDERS]).delete()


class Migration(migrations.Migration):
    dependencies = [("reference", "0003_country_pricing_market")]

    operations = [migrations.RunPython(add, remove)]
