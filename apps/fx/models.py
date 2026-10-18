from django.db import models
from django.db.models import Q


class FxMidRate(models.Model):
    """Mid-market (interbank) reference rate: 1 ``base`` = ``rate`` ``quote``.

    TimescaleDB hypertable partitioned on ``observed_at``. The primary key includes the
    time column (a hypertable requirement), which also makes re-ingesting the same
    observation idempotent.
    """

    class Source(models.TextChoices):
        OPEN_EXCHANGE_RATES = "openexchangerates", "Open Exchange Rates"
        EXCHANGE_RATE_API = "exchangerate_api", "ExchangeRate-API"
        CURRENCY_FREAKS = "currencyfreaks", "CurrencyFreaks"
        DERIVED = "derived", "Derived cross rate"
        MANUAL = "manual", "Manual entry"
        IMPORT = "import", "Historical import"

    pk = models.CompositePrimaryKey("base", "quote", "observed_at")
    base = models.ForeignKey("reference.Currency", on_delete=models.PROTECT, related_name="+")
    quote = models.ForeignKey("reference.Currency", on_delete=models.PROTECT, related_name="+")
    observed_at = models.DateTimeField(help_text="Timestamp of the rate according to the source.")
    rate = models.DecimalField(max_digits=24, decimal_places=10)
    source = models.CharField(max_length=32, choices=Source.choices)
    ingestion_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fx_mid_rates"
        constraints = [
            models.CheckConstraint(condition=Q(rate__gt=0), name="fx_mid_rate_positive"),
            models.CheckConstraint(
                condition=~Q(base=models.F("quote")), name="fx_mid_rate_distinct_currencies"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.base_id}/{self.quote_id} {self.rate} @ {self.observed_at:%Y-%m-%d %H:%M}"
