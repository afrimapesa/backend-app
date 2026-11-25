"""Add the remaining African currencies so the live FX feeds collect them too.

Only currencies are added: they get mid-market rates and history, but no countries or
corridors (the comparison still covers the six launch markets).
"""

from django.db import migrations

CURRENCIES = [
    # code, name, symbol, minor_units (ISO 4217)
    ("AOA", "Angolan Kwanza", "Kz", 2),
    ("BIF", "Burundian Franc", "FBu", 0),
    ("BWP", "Botswana Pula", "P", 2),
    ("CDF", "Congolese Franc", "FC", 2),
    ("CVE", "Cape Verdean Escudo", "Esc", 2),
    ("DJF", "Djiboutian Franc", "Fdj", 0),
    ("DZD", "Algerian Dinar", "DA", 2),
    ("ERN", "Eritrean Nakfa", "Nfk", 2),
    ("ETB", "Ethiopian Birr", "Br", 2),
    ("GMD", "Gambian Dalasi", "D", 2),
    ("GNF", "Guinean Franc", "FG", 0),
    ("KMF", "Comorian Franc", "CF", 0),
    ("LRD", "Liberian Dollar", "L$", 2),
    ("LSL", "Lesotho Loti", "L", 2),
    ("LYD", "Libyan Dinar", "LD", 3),
    ("MAD", "Moroccan Dirham", "DH", 2),
    ("MGA", "Malagasy Ariary", "Ar", 2),
    ("MRU", "Mauritanian Ouguiya", "UM", 2),
    ("MUR", "Mauritian Rupee", "Rs", 2),
    ("MWK", "Malawian Kwacha", "MK", 2),
    ("MZN", "Mozambican Metical", "MT", 2),
    ("NAD", "Namibian Dollar", "N$", 2),
    ("RWF", "Rwandan Franc", "FRw", 0),
    ("SCR", "Seychellois Rupee", "SR", 2),
    ("SDG", "Sudanese Pound", "", 2),
    ("SLE", "Sierra Leonean Leone", "Le", 2),
    ("SOS", "Somali Shilling", "Sh", 2),
    ("SSP", "South Sudanese Pound", "", 2),
    ("STN", "São Tomé and Príncipe Dobra", "Db", 2),
    ("SZL", "Eswatini Lilangeni", "E", 2),
    ("TND", "Tunisian Dinar", "DT", 3),
    ("UGX", "Ugandan Shilling", "USh", 0),
    ("XAF", "Central African CFA Franc", "FCFA", 0),
    ("XOF", "West African CFA Franc", "CFA", 0),
    ("ZMW", "Zambian Kwacha", "ZK", 2),
]


def add(apps, schema_editor):
    Currency = apps.get_model("reference", "Currency")
    for code, name, symbol, minor_units in CURRENCIES:
        Currency.objects.update_or_create(
            code=code, defaults={"name": name, "symbol": symbol, "minor_units": minor_units}
        )


def remove(apps, schema_editor):
    Currency = apps.get_model("reference", "Currency")
    FxMidRate = apps.get_model("fx", "FxMidRate")
    codes = [c[0] for c in CURRENCIES]
    FxMidRate.objects.filter(quote_id__in=codes).delete()
    FxMidRate.objects.filter(base_id__in=codes).delete()
    Currency.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("reference", "0004_euro_area_senders"),
        ("fx", "0004_source_sample"),
    ]

    operations = [migrations.RunPython(add, remove)]
