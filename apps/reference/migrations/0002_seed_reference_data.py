"""Seed the V1.0 reference data from the strategy doc (§2, §3.2).

Data is inlined (not imported) so this migration stays reproducible as the code evolves.
"""

from datetime import timedelta

from django.db import migrations

CURRENCIES = [
    # code, name, symbol, minor_units
    ("USD", "US Dollar", "$", 2),
    ("GBP", "Pound Sterling", "£", 2),
    ("EUR", "Euro", "€", 2),
    ("NGN", "Nigerian Naira", "₦", 2),
    ("GHS", "Ghanaian Cedi", "GH₵", 2),
    ("KES", "Kenyan Shilling", "KSh", 2),
    ("TZS", "Tanzanian Shilling", "TSh", 2),
    ("EGP", "Egyptian Pound", "E£", 2),
    ("ZAR", "South African Rand", "R", 2),
]

SENDING = [
    # code, name, kind, currency
    ("US", "United States", "country", "USD"),
    ("GB", "United Kingdom", "country", "GBP"),
    ("EU", "European Union", "region", "EUR"),
]

RECEIVING = [
    # code, name, currency, central bank, central bank code
    ("NG", "Nigeria", "NGN", "Central Bank of Nigeria", "CBN"),
    ("GH", "Ghana", "GHS", "Bank of Ghana", "BoG"),
    ("KE", "Kenya", "KES", "Central Bank of Kenya", "CBK"),
    ("TZ", "Tanzania", "TZS", "Bank of Tanzania", "BoT"),
    ("EG", "Egypt", "EGP", "Central Bank of Egypt", "CBE"),
    ("ZA", "South Africa", "ZAR", "South African Reserve Bank", "SARB"),
]

ALL_SENDING = ["US", "GB", "EU"]
ALL_RECEIVING = ["NG", "GH", "KE", "TZ", "EG", "ZA"]

FIVE_MIN = timedelta(minutes=5)
HOURLY = timedelta(hours=1)
THREE_HOURS = timedelta(hours=3)

PROVIDERS = [
    # slug, name, website, method, interval, sending, receiving
    ("wise", "Wise", "https://wise.com", "public_api", FIVE_MIN,
     ALL_SENDING, ["NG", "GH", "KE", "ZA", "EG"]),
    ("remitly", "Remitly", "https://www.remitly.com", "headless", HOURLY,
     ALL_SENDING, ALL_RECEIVING),
    ("worldremit", "WorldRemit", "https://www.worldremit.com", "internal_api", HOURLY,
     ALL_SENDING, ALL_RECEIVING),
    ("western-union", "Western Union", "https://www.westernunion.com", "html", THREE_HOURS,
     ALL_SENDING, ALL_RECEIVING),
    ("moneygram", "MoneyGram", "https://www.moneygram.com", "html", THREE_HOURS,
     ALL_SENDING, ALL_RECEIVING),
    ("lemfi", "LemFi", "https://lemfi.com", "mobile_api", HOURLY,
     ALL_SENDING, ["NG", "GH", "KE", "TZ"]),
    ("sendwave", "Sendwave", "https://www.sendwave.com", "mobile_api", HOURLY,
     ALL_SENDING, ["NG", "GH", "KE", "TZ", "EG"]),
    ("nala", "NALA", "https://www.nala.com", "partner_api", HOURLY,
     ALL_SENDING, ["NG", "GH", "KE", "TZ", "ZA"]),
    ("chipper-cash", "Chipper Cash", "https://www.chippercash.com", "partner_api", HOURLY,
     ["US", "GB"], ["NG", "GH", "KE", "ZA"]),
    ("flutterwave", "Send by Flutterwave", "https://send.flutterwave.com", "public_api", HOURLY,
     ALL_SENDING, ALL_RECEIVING),
    ("opay", "OPay", "https://www.opayweb.com", "mobile_api", HOURLY,
     ALL_SENDING, ["NG", "EG"]),
    ("revolut", "Revolut", "https://www.revolut.com", "public_api", HOURLY,
     ["GB", "EU"], ["NG", "GH", "KE", "ZA", "EG"]),
    ("taptap-send", "Taptap Send", "https://www.taptapsend.com", "mobile_api", HOURLY,
     ALL_SENDING, ["NG", "GH", "KE", "EG"]),
    ("ofx", "OFX", "https://www.ofx.com", "public_api", THREE_HOURS,
     ALL_SENDING, ["ZA", "KE", "NG"]),
    ("xe", "XE Money Transfer", "https://www.xe.com", "public_api", HOURLY,
     ALL_SENDING, ALL_RECEIVING),
]  # fmt: skip


def seed(apps, schema_editor):
    Currency = apps.get_model("reference", "Currency")
    Country = apps.get_model("reference", "Country")
    Corridor = apps.get_model("reference", "Corridor")
    Provider = apps.get_model("reference", "Provider")

    for code, name, symbol, minor_units in CURRENCIES:
        Currency.objects.update_or_create(
            code=code, defaults={"name": name, "symbol": symbol, "minor_units": minor_units}
        )

    for code, name, kind, currency in SENDING:
        Country.objects.update_or_create(
            code=code,
            defaults={"name": name, "kind": kind, "currency_id": currency, "is_sending": True},
        )
    for code, name, currency, bank, bank_code in RECEIVING:
        Country.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "currency_id": currency,
                "is_receiving": True,
                "central_bank": bank,
                "central_bank_code": bank_code,
            },
        )

    corridors = {}
    for send in Country.objects.filter(is_sending=True):
        for recv in Country.objects.filter(is_receiving=True):
            corridor, _ = Corridor.objects.get_or_create(
                send_country=send,
                send_currency_id=send.currency_id,
                receive_country=recv,
                receive_currency_id=recv.currency_id,
            )
            corridors[(send.code, recv.code)] = corridor

    for slug, name, website, method, interval, sending, receiving in PROVIDERS:
        provider, _ = Provider.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "website": website,
                "integration_method": method,
                "update_interval": interval,
            },
        )
        provider.corridors.set([corridors[(s, r)] for s in sending for r in receiving])


def unseed(apps, schema_editor):
    for model in ("Provider", "Corridor", "Country", "Currency"):
        apps.get_model("reference", model).objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("reference", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
