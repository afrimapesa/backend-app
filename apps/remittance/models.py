from decimal import Decimal

from django.db import models
from django.db.models import Q

from . import engine


class ProviderQuote(models.Model):
    """A provider's offer on a corridor at a point in time (TimescaleDB hypertable).

    Stores the inputs the calculation engine needs (rate, fee schedule, limits); payouts
    and rankings are computed per request amount, never stored.
    """

    class Source(models.TextChoices):
        ADAPTER = "adapter", "Automated adapter"
        MANUAL = "manual", "Manual override"

    pk = models.CompositePrimaryKey("provider", "corridor", "observed_at")
    provider = models.ForeignKey(
        "reference.Provider", on_delete=models.PROTECT, related_name="quotes"
    )
    corridor = models.ForeignKey(
        "reference.Corridor", on_delete=models.PROTECT, related_name="quotes"
    )
    observed_at = models.DateTimeField()
    fx_rate = models.DecimalField(
        max_digits=24,
        decimal_places=10,
        help_text="Receiving-currency units per 1 sending-currency unit.",
    )
    fee_flat = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal(0))
    fee_pct = models.DecimalField(
        max_digits=9, decimal_places=8, default=Decimal(0), help_text="Fraction: 0.015 = 1.5%."
    )
    min_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    transfer_time = models.DurationField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.ADAPTER)
    ingestion_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    raw = models.JSONField(
        default=dict, blank=True, help_text="Source payload excerpt, for debugging and audits."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "provider_quotes"
        indexes = [
            # Latest quotes for a corridor across all providers (compare endpoint).
            models.Index(fields=["corridor", "-observed_at"], name="quote_corridor_recent"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(fx_rate__gt=0), name="quote_fx_rate_positive"),
            models.CheckConstraint(
                condition=Q(fee_flat__gte=0), name="quote_fee_flat_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(fee_pct__gte=0) & Q(fee_pct__lt=1), name="quote_fee_pct_fraction"
            ),
            models.CheckConstraint(
                condition=Q(min_amount__isnull=True)
                | Q(max_amount__isnull=True)
                | Q(min_amount__lte=models.F("max_amount")),
                name="quote_min_le_max",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider_id} {self.corridor_id} {self.fx_rate} @ {self.observed_at:%H:%M}"

    def to_engine(self) -> engine.ProviderQuote:
        """Convert to the calculation engine's input type."""
        return engine.ProviderQuote(
            provider=self.provider.slug,
            fx_rate=self.fx_rate,
            fee=engine.FeeSchedule(flat=self.fee_flat, pct=self.fee_pct),
            observed_at=self.observed_at,
            update_interval=self.provider.update_interval,
            transfer_time=self.transfer_time,
            min_amount=self.min_amount,
            max_amount=self.max_amount,
        )
