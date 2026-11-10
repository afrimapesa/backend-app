from datetime import timedelta
from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.insights import front
from apps.insights.models import Advertisement, Article, Author

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def now():
    return timezone.now()


@pytest.fixture
def desk():
    return Author.objects.create(name="Markets Desk", slug="markets-desk", role="Currencies")


def make(slug, *, hours=1, section=Article.Section.CURRENCIES, kind=Article.Kind.NEWS, **kw):
    kw.setdefault("status", Article.Status.PUBLISHED)
    kw.setdefault("published_at", timezone.now() - timedelta(hours=hours))
    return Article.objects.create(
        slug=slug,
        title=slug.replace("-", " ").title(),
        standfirst="Standfirst.",
        body=kw.pop("body", "One two three."),
        section=section,
        kind=kind,
        **kw,
    )


def test_live_excludes_drafts_and_scheduled(now):
    make("live")
    make("draft", status=Article.Status.DRAFT)
    make("later", published_at=now + timedelta(hours=1))
    assert [a.slug for a in Article.objects.live(now)] == ["live"]


def test_reading_minutes():
    assert make("short").reading_minutes == 1
    assert make("long", body="word " * 500).reading_minutes == 3


def test_running_ads(now):
    common = dict(
        advertiser="A",
        placement="rail",
        image_url="https://a.example/x.png",
        click_url="https://a.example",
        alt_text="A",
        starts_at=now - timedelta(hours=1),
    )
    Advertisement.objects.create(name="on", **common)
    Advertisement.objects.create(name="off", is_active=False, **common)
    Advertisement.objects.create(name="ended", ends_at=now - timedelta(minutes=1), **common)
    Advertisement.objects.create(name="future", **{**common, "starts_at": now + timedelta(days=1)})
    assert [a.name for a in Advertisement.objects.running(now)] == ["on"]


def test_front_page_layout(now, desk):
    make("featured-old", hours=10, is_featured=True, author=desk)
    for i in range(6):
        make(f"news-{i}", hours=i + 1)
    make("bond-explainer", hours=20, section=Article.Section.BONDS, kind=Article.Kind.EXPLAINER)
    make("opinion", hours=30, kind=Article.Kind.OPINION)

    page = front.build(now=now)

    assert page["lead"]["slug"] == "featured-old"  # featured beats newer
    assert page["lead"]["author"] == {
        "slug": "markets-desk",
        "name": "Markets Desk",
        "role": "Currencies",
    }
    assert [a["slug"] for a in page["top"]] == ["news-0", "news-1", "news-2", "news-3"]
    assert page["latest"][0]["slug"] == "news-0"
    sections = {s["key"]: [a["slug"] for a in s["articles"]] for s in page["sections"]}
    # Sections avoid repeating the lead and top stories.
    assert sections["currencies"] == ["news-4", "news-5", "opinion"]
    assert sections["bonds"] == ["bond-explainer"]
    assert page["sections"][0]["label"] == "Currencies"
    assert [a["slug"] for a in page["commentary"]] == ["opinion"]
    assert [a["slug"] for a in page["explainers"]] == ["bond-explainer"]
    assert page["ads"] == {"leaderboard": None, "rail": None, "inline": None}
    assert page["sample"] is False


def test_front_page_empty(now):
    page = front.build(now=now)
    assert page["lead"] is None and page["top"] == [] and page["sections"] == []


def test_front_page_is_cached_and_invalidated_on_commit(
    now, django_assert_num_queries, django_capture_on_commit_callbacks
):
    make("first")
    assert front.front_page(now=now)["lead"]["slug"] == "first"
    with django_assert_num_queries(0):
        front.front_page(now=now)

    with django_capture_on_commit_callbacks(execute=True):
        make("second", hours=0, is_featured=True)
    assert front.front_page(now=timezone.now())["lead"]["slug"] == "second"


def test_front_endpoint(client, desk):
    make("a", author=desk)
    Advertisement.objects.create(
        name="c",
        advertiser="Acme",
        placement="leaderboard",
        image_url="https://a.example/x.png",
        click_url="https://a.example",
        alt_text="Acme",
    )
    body = client.get(reverse("insights-front")).json()
    assert body["lead"]["slug"] == "a"
    assert body["lead"]["section"] == {"key": "currencies", "label": "Currencies"}
    assert body["ads"]["leaderboard"]["advertiser"] == "Acme"
    assert "as_of" in body


def test_article_list_filters(client):
    ng = make("naira", section=Article.Section.CURRENCIES)
    ng.countries.set(["NG"])
    make("bonds", hours=2, section=Article.Section.BONDS, kind=Article.Kind.EXPLAINER)
    make("draft", status=Article.Status.DRAFT)
    url = reverse("insights-articles")

    def slugs(**params):
        return [a["slug"] for a in client.get(url, params).json()["results"]]

    assert slugs() == ["naira", "bonds"]
    assert slugs(section="bonds") == ["bonds"]
    assert slugs(kind="explainer") == ["bonds"]
    assert slugs(country="ng") == ["naira"]
    assert client.get(url).json()["results"][0]["countries"] == ["NG"]


def test_article_detail(client):
    make("main", body="Para one.\n\nPara two.")
    make("related", hours=2)
    make("elsewhere", section=Article.Section.BONDS)
    body = client.get(reverse("insights-article", args=["main"])).json()
    assert body["article"]["body"] == "Para one.\n\nPara two."
    assert [a["slug"] for a in body["related"]] == ["related"]


def test_article_detail_hides_drafts(client):
    make("hidden", status=Article.Status.DRAFT)
    assert client.get(reverse("insights-article", args=["hidden"])).status_code == 404


def test_seed_sample_articles_replaces_previous_set():
    out = StringIO()
    call_command("seed_sample_articles", stdout=out)
    call_command("seed_sample_articles", stdout=out)
    articles = Article.objects.live()
    assert articles.count() == articles.filter(sample=True).count() > 10
    assert articles.filter(is_featured=True).exists()
    assert (
        Article.objects.get(slug__startswith="reading-the-naira")
        .countries.filter(code="NG")
        .exists()
    )
    page = front.build(now=timezone.now())
    assert page["sample"] is True and len(page["sections"]) >= 5

    call_command("seed_sample_articles", "--clear", stdout=out)
    assert not Article.objects.filter(sample=True).exists()
