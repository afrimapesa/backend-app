# ruff: noqa: E501  (article bodies are prose, one paragraph per line)
"""Seed placeholder articles so the news pages can be previewed before editors write any.

The pieces are evergreen explainers and commentary under desk bylines: no invented news
events, no made-up people, no provider named. Every one is flagged ``sample`` and the
site labels them. Re-running replaces the previous sample set (and re-dates it to now).
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.insights.models import Article, Author
from apps.reference.models import Country

DESKS = {
    "markets": ("AFRIMAPESA Markets Desk", "Currencies and rates"),
    "research": ("AFRIMAPESA Research", "Data and methodology"),
    "editorial": ("AFRIMAPESA Editorial", "Comment"),
}

S, K = Article.Section, Article.Kind

# (hours ago, desk, section, kind, countries, currency, featured, title, standfirst, body)
ARTICLES = [
    (
        1,
        "research",
        S.REMITTANCE,
        K.EXPLAINER,
        [],
        None,
        True,
        "The fee is the small print: why the exchange rate decides what your family receives",
        "A transfer advertised as free can still cost more than one with a fee. The difference "
        "hides in the rate.",
        """Most money transfer services earn in two places: the fee you see, and the margin they add to the exchange rate, which you usually don't.

## The benchmark

The mid-market rate is the midpoint between what banks pay to buy and sell a currency. It is the fairest single reference for what a currency is worth at that moment, and it is the rate every quote on AFRIMAPESA is measured against.

## Where the margin goes

If the mid-market rate is 2,000 and a service offers 1,960, the 40 difference on every unit is a cost. On a 200 transfer that can be worth more than the fee itself.

## How we compare

We convert every quote into one number: what arrives at the other end. Fees and rate margins are added together as the total cost, so a free transfer and a paid one can be compared fairly.""",
    ),
    (
        3,
        "markets",
        S.CURRENCIES,
        K.ANALYSIS,
        ["NG"],
        "NGN",
        True,
        "Reading the naira: what moves Nigeria's currency against the dollar",
        "Oil receipts, central bank policy and diaspora inflows all leave their mark on NGN. "
        "Here is how to read them.",
        """The naira is one of the most watched currencies in Africa, and one of the most misunderstood.

## Dollar supply

Nigeria earns most of its foreign currency from oil exports. When those earnings rise, more dollars reach the market and pressure on the naira eases; when they fall, the opposite happens.

## Policy

The Central Bank of Nigeria's decisions on interest rates and on how the official market operates shape both the level of the rate and how much it moves from day to day.

## Diaspora flows

Money sent home by Nigerians abroad is a large and steady source of dollars. Seasonal peaks, such as the end of the year, are worth watching on the chart above.""",
    ),
    (
        5,
        "markets",
        S.CURRENCIES,
        K.ANALYSIS,
        ["ZA"],
        "ZAR",
        False,
        "The rand as a risk barometer: why ZAR moves with global markets",
        "South Africa's currency is traded around the clock by investors far from Johannesburg. "
        "That makes it unusually sensitive to global mood.",
        """The rand is one of the most liquid emerging-market currencies, which means it is often the first to move when global investors change their minds about risk.

## Global appetite

When investors are confident, money flows into higher-yielding markets and the rand tends to strengthen. When they are nervous, it is often sold quickly.

## Commodities

Gold, platinum and coal exports link the rand to commodity prices. A rise in metals prices can support it even on otherwise quiet days.

## What it means for transfers

Because the rand can move more within a day than many currencies, comparing quotes close to the moment you send matters more than usual.""",
    ),
    (
        7,
        "markets",
        S.CURRENCIES,
        K.EXPLAINER,
        ["EG"],
        "EGP",
        False,
        "Egypt's pound: understanding official and market exchange rates",
        "When a currency has more than one price, knowing which one a quote uses is the "
        "difference between a good deal and a poor one.",
        """Several African currencies have, at times, traded at different prices in different places. Egypt's pound is a well-known example.

## Official rates

The official rate is the one published by the central bank and used by banks for most regulated transactions.

## Why gaps open

When demand for foreign currency is larger than the supply available through official channels, a gap can open between the official rate and the prices people are willing to pay elsewhere.

## How AFRIMAPESA handles it

We publish the mid-market reference rate from regulated sources and compare provider quotes against it, so any gap shows up as a cost, not as a hidden surprise.""",
    ),
    (
        9,
        "research",
        S.BONDS,
        K.EXPLAINER,
        [],
        None,
        False,
        "Treasury bills in plain English: 91, 182 and 364 days",
        "T-bills are the simplest way to lend to a government. Here is how the discount, the "
        "tenor and the yield fit together.",
        """A Treasury bill is a short-term loan to a government. You pay less than its face value today and receive the full face value when it matures.

## The discount

If a 364-day bill with a face value of 100 sells for 85, the 15 difference is your return.

## The tenor

Governments usually issue bills for 91, 182 and 364 days. Longer tenors normally pay more, because your money is tied up for longer.

## Real returns

A high yield is only half the story. Subtract inflation to see what the investment really earns, which is what our bonds section will show.""",
    ),
    (
        12,
        "research",
        S.BONDS,
        K.EXPLAINER,
        [],
        None,
        False,
        "Eurobonds or local bonds? Two ways to lend to an African government",
        "One pays in dollars, the other in local currency. The trade-off is between yield and "
        "currency risk.",
        """African governments borrow in two main ways: in their own currency at home, and in dollars or euros on international markets through Eurobonds.

## Local-currency bonds

These usually pay higher interest. But if the local currency weakens, the value of those payments falls for a foreign investor.

## Eurobonds

These pay in hard currency, so currency risk is removed. Yields are lower, and the main risk becomes the government's ability to repay.

## Comparing them fairly

Comparing the two means adjusting for expected currency moves and inflation, not just reading the headline yield.""",
    ),
    (
        15,
        "research",
        S.BANKING,
        K.EXPLAINER,
        ["KE", "NG", "GH"],
        None,
        False,
        "A high deposit rate can still lose you money. Here is how to check",
        "The rate on a savings account means little until you set it against inflation.",
        """Banks across Africa advertise deposit rates that can look generous to savers abroad. The figure that matters is the real rate.

## The real rate

Real rate = deposit rate minus inflation. A 12% account in a country with 15% inflation loses purchasing power every year.

## Fixed or flexible

Fixed deposits often pay more in exchange for locking your money away. Check the penalty for early withdrawal.

## What we are building

AFRIMAPESA's savings section will show deposit rates by bank alongside inflation, so the real return is visible at a glance.""",
    ),
    (
        19,
        "markets",
        S.ECONOMY,
        K.EXPLAINER,
        [],
        None,
        False,
        "How central banks set interest rates, and why it moves your currency",
        "Policy rates influence borrowing, inflation and the value of a currency. A short guide "
        "to the decisions that move markets.",
        """Every central bank on our coverage list meets regularly to set a policy rate, the interest rate that anchors the rest of the economy.

## Raising rates

Higher rates make borrowing more expensive and saving more attractive. They are usually used to bring inflation down, and can make a currency more attractive to hold.

## Cutting rates

Lower rates support borrowing and growth, but can weigh on the currency if they fall too far below inflation.

## Reading the decision

Markets react to surprises, not to decisions everyone expected. The statement explaining the decision often matters as much as the rate itself.""",
    ),
    (
        23,
        "markets",
        S.REMITTANCE,
        K.ANALYSIS,
        ["KE"],
        "KES",
        False,
        "Sending money to Kenya: what to compare beyond the fee",
        "Delivery speed, payout method and the rate all differ by provider. Here is a checklist "
        "for the Kenya corridor.",
        """Kenya has one of the most developed mobile money systems in the world, which shapes how money sent from abroad is received.

## Payout method

Mobile wallet, bank account or cash pickup: each can carry a different fee and a different rate from the same provider.

## Speed

Transfers to mobile wallets are often near-instant. Bank deposits can take longer, especially over weekends.

## The total

Compare what arrives, not what is advertised. Our comparison table ranks every provider on that single number.""",
    ),
    (
        28,
        "markets",
        S.REMITTANCE,
        K.EXPLAINER,
        ["TZ"],
        "TZS",
        False,
        "Is there a best day to send money home?",
        "Rates move every day, but timing a transfer is harder than it sounds. What our data will "
        "be able to show.",
        """It is tempting to wait for a better rate before sending money. In practice, small daily moves are often outweighed by the gap between providers.

## Rates move constantly

Currency prices change throughout the trading day and are quieter at weekends, when some providers widen their margins.

## Provider spread matters more

On most days, choosing a cheaper provider saves more than waiting for the market.

## What we are tracking

As AFRIMAPESA collects quotes over time, we will publish how margins change by day of the week on each corridor.""",
    ),
    (
        34,
        "editorial",
        S.REMITTANCE,
        K.OPINION,
        [],
        None,
        False,
        "Price transparency should be the norm for money sent to Africa",
        "Families lose money to costs they were never shown. Clear, comparable pricing would "
        "change that.",
        """Sending money to Sub-Saharan Africa remains among the most expensive remittance routes in the world, and much of that cost is not on the receipt.

## The hidden part

A transfer fee is easy to see. A margin built into the exchange rate is not, and it often costs more.

## A simple standard

Every quote could show the mid-market rate next to the rate offered, and the total cost in the sender's currency. Some providers already do.

## Why we compare

Independent comparison, ranked by what arrives and not by who pays, puts that information in front of senders before they choose.""",
    ),
    (
        40,
        "editorial",
        S.BANKING,
        K.OPINION,
        [],
        None,
        False,
        "Africa's diaspora is a saver as well as a sender",
        "Money sent home is only part of the story. Many abroad also want a safe, well-paying "
        "place to save in their home market.",
        """Remittances get most of the attention, but many people abroad also hold savings in their home country, or would like to.

## The information gap

Deposit rates, terms and protections vary widely between banks and are rarely published in one place.

## What would help

Comparable data: the rate, the term, the minimum deposit and the real return after inflation, side by side.

## Where we come in

That is the gap AFRIMAPESA's savings section is being built to close.""",
    ),
    (
        46,
        "markets",
        S.CURRENCIES,
        K.ANALYSIS,
        ["GH"],
        "GHS",
        False,
        "The cedi's seasons: how gold and cocoa shape Ghana's currency",
        "Ghana's export calendar leaves a pattern in its currency. Knowing it helps explain the "
        "moves on the chart.",
        """Ghana earns foreign currency mainly from gold, cocoa and oil, and the timing of those earnings matters for the cedi.

## Export receipts

When exporters convert their earnings, the extra supply of dollars can support the cedi.

## Import demand

Demand for dollars to pay for imports, including fuel, works the other way.

## Reading the chart

Our 3-month trend shows the result of these forces. Longer history, once imported, will make seasonal patterns easier to see.""",
    ),
    (
        52,
        "research",
        S.MARKETS,
        K.EXPLAINER,
        [],
        None,
        False,
        "How AFRIMAPESA ranks money transfer providers",
        "One rule decides the order: what arrives. Nobody can pay to move up.",
        """Our ranking is mechanical and the same for every provider.

## What arrives

For the amount you enter, we calculate what the recipient gets after fees and the exchange rate. The highest payout ranks first.

## Ties

When two payouts are equal, the lower fee ranks first, then the faster transfer.

## Freshness

Every quote shows its age. Quotes older than twice a provider's normal update interval are flagged and ranked after fresh ones.

## Independence

Advertising on AFRIMAPESA never changes a ranking, and adverts never appear inside the comparison.""",
    ),
    (
        60,
        "markets",
        S.MARKETS,
        K.EXPLAINER,
        [],
        None,
        False,
        "What the mid-market rate is, and why we use it",
        "It is the benchmark behind every number on this site. Here is where it comes from.",
        """The mid-market rate is the midpoint between the buy and sell prices of a currency in the wholesale market.

## Why it is fair

Neither the buyer nor the seller is favoured, so it is the closest thing to the true price at a moment in time.

## Where ours comes from

We collect rates from regulated and central bank sources, and cross through the US dollar where a direct rate is not published.

## How to use it

Compare any rate you are offered with the mid-market rate. The difference, multiplied by your amount, is what the margin costs you.""",
    ),
    (
        70,
        "markets",
        S.ECONOMY,
        K.ANALYSIS,
        ["NG", "GH", "KE", "TZ", "EG", "ZA"],
        None,
        False,
        "Six economies, six currencies: a guide to AFRIMAPESA's coverage",
        "Nigeria, Ghana, Kenya, Tanzania, Egypt and South Africa: what links them, and what sets "
        "each apart.",
        """Our first six markets account for a large share of the money sent to Africa each year.

## Commodity exporters

Nigeria and Ghana earn heavily from oil, gold and cocoa, which ties their currencies to commodity prices.

## Diversified economies

South Africa and Egypt have broader economies and deeper financial markets, with currencies traded widely abroad.

## East Africa

Kenya and Tanzania have fast-growing digital payment systems, which shape how remittances are received.

## What comes next

More countries are added as data becomes available, as rows in our reference data rather than new code.""",
    ),
]


class Command(BaseCommand):
    help = "Create (or replace) the sample articles used to preview the news pages."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Only delete sample articles.")

    @transaction.atomic
    def handle(self, *args, clear: bool = False, **options):
        deleted, _ = Article.objects.filter(sample=True).delete()
        if clear:
            self.stdout.write(f"Deleted {deleted} sample articles.")
            return

        desks = {}
        for key, (name, role) in DESKS.items():
            desks[key], _ = Author.objects.update_or_create(
                slug=f"afrimapesa-{key}", defaults={"name": name, "role": role}
            )
        known = set(Country.objects.values_list("code", flat=True))
        now = timezone.now()
        for (
            hours,
            desk,
            section,
            kind,
            countries,
            currency,
            featured,
            title,
            standfirst,
            body,
        ) in ARTICLES:
            article = Article.objects.create(
                slug=_slugify(title),
                title=title,
                standfirst=standfirst,
                body=body,
                kind=kind,
                section=section,
                currency_id=currency,
                author=desks[desk],
                status=Article.Status.PUBLISHED,
                published_at=now - timedelta(hours=hours, minutes=7 * hours % 50),
                is_featured=featured,
                sample=True,
            )
            article.countries.set([c for c in countries if c in known])
            # auto_now stamped today; a sample piece was never edited after publishing.
            Article.objects.filter(pk=article.pk).update(updated_at=article.published_at)
        self.stdout.write(self.style.SUCCESS(f"Created {len(ARTICLES)} sample articles."))


def _slugify(title: str) -> str:
    return slugify(title)[:150].rstrip("-")
