"""The news front page, assembled in one pass and cached in Redis.

Any change to an article, author or advertisement drops the cache (see ``signals``), so
editors see their changes at once; otherwise the page is rebuilt at most every
``CACHE_TTL`` seconds, which is also how late a scheduled article can appear.
"""

from __future__ import annotations

from datetime import datetime

from django.core.cache import cache

from .models import Advertisement, Article
from .serializers import AdvertisementSerializer, ArticleCardSerializer

CACHE_KEY = "insights:front:v1"
CACHE_TTL = 60
POOL = 200  # most recent live articles considered for the page

TOP_COUNT = 4
LATEST_COUNT = 15
SECTION_COUNT = 4
COMMENTARY_COUNT = 4
EXPLAINER_COUNT = 5


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def front_page(*, now: datetime) -> dict:
    page = cache.get(CACHE_KEY)
    if page is None:
        page = build(now=now)
        cache.set(CACHE_KEY, page, CACHE_TTL)
    return page


def build(*, now: datetime) -> dict:
    articles = list(
        Article.objects.live(now).select_related("author").prefetch_related("countries")[:POOL]
    )
    cards = {a.pk: dict(ArticleCardSerializer(a).data) for a in articles}

    def pick(items, limit, *, exclude=frozenset()):
        return [cards[a.pk] for a in items if a.pk not in exclude][:limit]

    featured = [a for a in articles if a.is_featured]
    lead = featured[0] if featured else (articles[0] if articles else None)
    # Top stories: other featured pieces first, then the newest of the rest.
    top_pool = featured[1:] + [a for a in articles if not a.is_featured]
    top = [a for a in top_pool if a is not lead][:TOP_COUNT]
    on_top = {a.pk for a in top} | ({lead.pk} if lead else set())

    sections = []
    for section in Article.Section:
        in_section = [a for a in articles if a.section == section]
        chosen = pick(in_section, SECTION_COUNT, exclude=on_top) or pick(in_section, SECTION_COUNT)
        if chosen:
            sections.append({"key": section.value, "label": section.label, "articles": chosen})

    commentary_kinds = {Article.Kind.OPINION, Article.Kind.ANALYSIS}
    ads = {}
    for placement in Advertisement.Placement:
        ad = Advertisement.objects.running(now).filter(placement=placement).first()
        ads[placement.value] = dict(AdvertisementSerializer(ad).data) if ad else None

    return {
        "sample": any(a.sample for a in articles),
        "lead": cards[lead.pk] if lead else None,
        "top": [cards[a.pk] for a in top],
        "latest": pick(articles, LATEST_COUNT),
        "sections": sections,
        "commentary": pick([a for a in articles if a.kind in commentary_kinds], COMMENTARY_COUNT),
        "explainers": pick(
            [a for a in articles if a.kind == Article.Kind.EXPLAINER], EXPLAINER_COUNT
        ),
        "ads": ads,
    }
