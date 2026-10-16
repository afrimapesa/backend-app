from django.db import models
from django.db.models import Q


class IngestionRun(models.Model):
    """One execution of an ingestion adapter (FX feed, provider scraper, ...).

    Every run is logged, success or failure, so the scraper health dashboard (T25) and
    the reliability exit criterion (E02: >=95% successful runs) can be computed from it.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial (some records rejected)"
        FAILED = "failed", "Failed"

    source = models.CharField(
        max_length=64, db_index=True, help_text="Adapter name, e.g. 'wise' or 'openexchangerates'."
    )
    provider = models.ForeignKey(
        "reference.Provider",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_runs",
        help_text="Set for provider quote runs; empty for FX/CPI feeds.",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=1)
    records_fetched = models.PositiveIntegerField(default=0)
    records_stored = models.PositiveIntegerField(default=0)
    records_rejected = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    details = models.JSONField(
        default=dict, blank=True, help_text="Rejection reasons, response metadata, etc."
    )

    class Meta:
        db_table = "ingestion_runs"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["source", "-started_at"], name="ingestion_source_recent")]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=models.F("started_at")),
                name="ingestion_run_finished_after_start",
            ),
            models.CheckConstraint(
                condition=Q(status="running") | Q(finished_at__isnull=False),
                name="ingestion_run_finished_when_done",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source} @ {self.started_at:%Y-%m-%d %H:%M} ({self.status})"
