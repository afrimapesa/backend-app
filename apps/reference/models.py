"""Reference data shared by every module: currencies, countries, remittance corridors, providers.

New countries and corridors are added as rows, not code (strategy doc §2).
"""

from datetime import timedelta

from django.conf import settings
from django.db import models


class Currency(models.Model):
    code = models.CharField(max_length=3, primary_key=True, help_text="ISO 4217 code, e.g. NGN")
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=8, blank=True)
    minor_units = models.PositiveSmallIntegerField(
        default=2, help_text="Decimal places used when displaying amounts."
    )

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "currencies"

    def __str__(self) -> str:
        return self.code


class Country(models.Model):
    """A sending market (US, UK, EU) or a receiving country (NG, GH, ...).

    The EU is modelled as a market with the ISO-reserved code ``EU`` because corridors
    are priced per sending currency, not per member state.
    """

    class Kind(models.TextChoices):
        COUNTRY = "country", "Country"
        REGION = "region", "Region"

    code = models.CharField(max_length=2, primary_key=True, help_text="ISO 3166-1 alpha-2")
    name = models.CharField(max_length=64)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.COUNTRY)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="countries")
    is_sending = models.BooleanField(default=False)
    is_receiving = models.BooleanField(default=False)
    central_bank = models.CharField(max_length=128, blank=True)
    central_bank_code = models.CharField(max_length=16, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "countries"

    def __str__(self) -> str:
        return self.name


class Corridor(models.Model):
    """A remittance route, e.g. UK (GBP) -> Nigeria (NGN)."""

    send_country = models.ForeignKey(
        Country, on_delete=models.PROTECT, related_name="outbound_corridors"
    )
    send_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="+")
    receive_country = models.ForeignKey(
        Country, on_delete=models.PROTECT, related_name="inbound_corridors"
    )
    receive_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["send_country", "receive_country"]
        constraints = [
            models.UniqueConstraint(
                fields=["send_country", "send_currency", "receive_country", "receive_currency"],
                name="uniq_corridor",
            ),
            models.CheckConstraint(
                condition=~models.Q(send_country=models.F("receive_country")),
                name="corridor_distinct_countries",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code}"

    @property
    def code(self) -> str:
        """Stable identifier used in URLs and cache keys, e.g. ``GB-GBP-NG-NGN``."""
        return (
            f"{self.send_country_id}-{self.send_currency_id}-"
            f"{self.receive_country_id}-{self.receive_currency_id}"
        )


class Provider(models.Model):
    """A money transfer operator or fintech whose quotes we compare."""

    class IntegrationMethod(models.TextChoices):
        PUBLIC_API = "public_api", "Public API"
        PARTNER_API = "partner_api", "Partner API"
        INTERNAL_API = "internal_api", "Internal API"
        MOBILE_API = "mobile_api", "Mobile app API"
        HEADLESS = "headless", "Headless browser"
        HTML = "html", "HTML scraping"
        MANUAL = "manual", "Manual entry"

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    website = models.URLField(blank=True)
    integration_method = models.CharField(max_length=20, choices=IntegrationMethod.choices)
    update_interval = models.DurationField(
        default=timedelta(hours=1),
        help_text="Target refresh cadence. Quotes older than 2x this are flagged stale.",
    )
    corridors = models.ManyToManyField(Corridor, related_name="providers", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class UserPreference(models.Model):
    """Global country/region focus (strategy doc §1 note). Null focus = whole region."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preference"
    )
    focus_country = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"is_receiving": True},
    )
    send_country = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"is_sending": True},
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Preferences for {self.user}"
