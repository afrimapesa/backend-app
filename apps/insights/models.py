"""News & insights (strategy Pillar 4): articles written in-house or by invited experts.

Articles are written and published from the Django admin. Wire stories from Reuters or
Bloomberg would need a licence (development plan D05), so nothing here is syndicated.
Advertisements are separate records shown in labelled slots; they never touch rankings.
"""

from __future__ import annotations

import math

from django.db import models
from django.utils import timezone


class Author(models.Model):
    """A byline: a person or a desk (e.g. "AFRIMAPESA Markets Desk")."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    role = models.CharField(max_length=120, blank=True, help_text='e.g. "FX analyst"')
    bio = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ArticleQuerySet(models.QuerySet):
    def live(self, now=None) -> ArticleQuerySet:
        """Published and not scheduled for later."""
        return self.filter(status=Article.Status.PUBLISHED, published_at__lte=now or timezone.now())


class Article(models.Model):
    class Kind(models.TextChoices):
        NEWS = "news", "News"
        ANALYSIS = "analysis", "Analysis"
        OPINION = "opinion", "Opinion"
        EXPLAINER = "explainer", "Explainer"

    class Section(models.TextChoices):
        MARKETS = "markets", "Markets"
        CURRENCIES = "currencies", "Currencies"
        REMITTANCE = "remittance", "Money transfers"
        BONDS = "bonds", "Bonds"
        BANKING = "banking", "Savings & banking"
        ECONOMY = "economy", "Economy"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    slug = models.SlugField(max_length=160, unique=True)
    title = models.CharField(max_length=200)
    standfirst = models.CharField(
        max_length=320, help_text="One or two sentences under the headline."
    )
    body = models.TextField(
        help_text='Paragraphs separated by a blank line. Start a line with "## " for a subheading.'
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.NEWS)
    section = models.CharField(max_length=12, choices=Section.choices)
    countries = models.ManyToManyField("reference.Country", blank=True, related_name="articles")
    currency = models.ForeignKey(
        "reference.Currency",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Currency the story is about, if any (labels the cover art).",
    )
    author = models.ForeignKey(
        Author, on_delete=models.PROTECT, null=True, blank=True, related_name="articles"
    )
    cover_image_url = models.URLField(blank=True, help_text="Leave empty for generated cover art.")
    cover_credit = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_featured = models.BooleanField(
        default=False, help_text="Featured stories lead the front page."
    )
    sample = models.BooleanField(default=False, help_text="Placeholder content for the preview.")

    objects = ArticleQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at"]
        indexes = [models.Index(fields=["status", "-published_at"], name="article_live_idx")]

    def __str__(self) -> str:
        return self.title

    @property
    def reading_minutes(self) -> int:
        return max(1, math.ceil(len(self.body.split()) / 220))


class AdvertisementQuerySet(models.QuerySet):
    def running(self, now=None) -> AdvertisementQuerySet:
        now = now or timezone.now()
        return self.filter(is_active=True, starts_at__lte=now).filter(
            models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=now)
        )


class Advertisement(models.Model):
    """A paid placement in a labelled slot. Never shown inside the comparison tables."""

    class Placement(models.TextChoices):
        LEADERBOARD = "leaderboard", "Leaderboard (970×90, top of page)"
        RAIL = "rail", "Rail (300×250, side column)"
        INLINE = "inline", "In-article (728×90)"

    name = models.CharField(max_length=120, help_text="Internal campaign name.")
    advertiser = models.CharField(max_length=120)
    placement = models.CharField(max_length=12, choices=Placement.choices)
    image_url = models.URLField()
    click_url = models.URLField()
    alt_text = models.CharField(max_length=200)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    objects = AdvertisementQuerySet.as_manager()

    class Meta:
        ordering = ["placement", "-starts_at"]

    def __str__(self) -> str:
        return f"{self.advertiser}: {self.name}"
