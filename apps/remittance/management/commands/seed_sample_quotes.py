"""Write PREVIEW SAMPLE data: mid-market rates, 90 days of rate history and provider quotes.

    python manage.py seed_sample_quotes              # write one fresh set
    python manage.py seed_sample_quotes --loop 300   # keep refreshing every 5 minutes
    python manage.py seed_sample_quotes --clear      # delete all sample data

Everything written is tagged source="sample", so the API reports `sample: true` and the
site labels it. Real ingestion data is never touched. Remove this once live feeds run.
"""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.fx.models import FxMidRate
from apps.reference.models import Corridor, Provider
from apps.remittance import compare
from apps.remittance.models import ProviderQuote

SAMPLE = "sample"

# Approximate mid-market rates per 1 USD (illustrative only).
USD_TO = {
    "GBP": Decimal("0.75"),
    "EUR": Decimal("0.86"),
    "NGN": Decimal("1530"),
    "GHS": Decimal("15.4"),
    "KES": Decimal("129.2"),
    "TZS": Decimal("2655"),
    "EGP": Decimal("48.6"),
    "ZAR": Decimal("17.7"),
}

# Rough provider profiles: exchange-rate margin, flat fee, % fee, delivery minutes.
PROFILES = {
    "wise": (0.002, "0.79", "0.0045", 30),
    "remitly": (0.019, "0", "0", 60),
    "worldremit": (0.014, "1.99", "0", 120),
    "western-union": (0.035, "1.99", "0", 1440),
    "moneygram": (0.032, "3.99", "0", None),
    "lemfi": (0.006, "0", "0", 10),
    "sendwave": (0.011, "0", "0", 15),
    "nala": (0.008, "0", "0", 20),
    "chipper-cash": (0.013, "0", "0", 30),
    "flutterwave": (0.012, "0.99", "0", 60),
    "opay": (0.015, "0", "0", 30),
    "revolut": (0.005, "0", "0.005", 1440),
    "taptap-send": (0.009, "0", "0", 15),
    "ofx": (0.007, "0", "0", 2880),
    "xe": (0.01, "0", "0", 1440),
}

HISTORY_DAYS = 90


class Command(BaseCommand):
    help = "Write labelled sample FX rates and provider quotes for the preview."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete all sample data.")
        parser.add_argument(
            "--loop", type=int, metavar="SECONDS", help="Keep refreshing every SECONDS."
        )

    def handle(self, *args, clear: bool, loop: int | None, **options):
        if clear:
            quotes, _ = ProviderQuote.objects.filter(source=SAMPLE).delete()
            rates, _ = FxMidRate.objects.filter(source=SAMPLE).delete()
            compare.invalidate(Corridor.objects.values_list("pk", flat=True))
            self.stdout.write(f"Deleted {quotes} sample quotes and {rates} sample rates.")
            return
        while True:
            self.write_once()
            if not loop:
                return
            time.sleep(loop)

    def write_once(self) -> None:
        now = timezone.now()
        rng = random.Random()  # noqa: S311 - sample data, not security
        with transaction.atomic():
            rates = self._write_rates(now, rng)
            quotes = self._write_quotes(now, rates, rng)
        compare.invalidate(Corridor.objects.values_list("pk", flat=True))
        self.stdout.write(f"{now:%H:%M:%S} wrote {len(rates)} sample rates and {quotes} quotes")

    def _write_rates(self, now: datetime, rng: random.Random) -> dict[str, Decimal]:
        """USD legs only; other pairs are derived through USD, as for real feeds."""
        current: dict[str, Decimal] = {}
        for code, base_rate in USD_TO.items():
            last = (
                FxMidRate.objects.filter(base_id="USD", quote_id=code, source=SAMPLE)
                .order_by("-observed_at")
                .values_list("rate", flat=True)
                .first()
            )
            if last is None:
                self._write_history(code, base_rate, now, rng)
                last = base_rate
            # Small random walk (±0.1%) so the preview looks alive.
            current[code] = (last * Decimal(str(1 + rng.uniform(-0.001, 0.001)))).quantize(
                Decimal("0.000001")
            )
        FxMidRate.objects.bulk_create(
            [
                FxMidRate(base_id="USD", quote_id=c, rate=r, observed_at=now, source=SAMPLE)
                for c, r in current.items()
            ],
            ignore_conflicts=True,
        )
        return current

    def _write_history(
        self, code: str, end_rate: Decimal, now: datetime, rng: random.Random
    ) -> None:
        """One rate per day for HISTORY_DAYS, a random walk ending near today's rate."""
        today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        rate = float(end_rate)
        rows = []
        for back in range(1, HISTORY_DAYS):
            rate /= 1 + rng.uniform(-0.0028, 0.0032)
            rows.append(
                FxMidRate(
                    base_id="USD",
                    quote_id=code,
                    rate=Decimal(f"{rate:.6f}"),
                    observed_at=today - timedelta(days=back),
                    source=SAMPLE,
                )
            )
        FxMidRate.objects.bulk_create(rows, ignore_conflicts=True)

    def _write_quotes(self, now: datetime, usd_to: dict[str, Decimal], rng: random.Random) -> int:
        rows = []
        providers = Provider.objects.filter(is_active=True).prefetch_related(
            "corridors__send_currency", "corridors__receive_currency"
        )
        for provider in providers:
            profile = PROFILES.get(provider.slug)
            if profile is None:
                continue
            margin, flat, pct, minutes = profile
            for corridor in provider.corridors.all():
                send, receive = corridor.send_currency_id, corridor.receive_currency_id
                usd_send = Decimal(1) if send == "USD" else usd_to[send]
                mid = usd_to[receive] / usd_send
                m = max(0.0, margin + rng.uniform(-0.003, 0.003))
                rows.append(
                    ProviderQuote(
                        provider=provider,
                        corridor=corridor,
                        # Spread within the provider's refresh cycle, as real quotes would be.
                        observed_at=now
                        - timedelta(
                            seconds=rng.uniform(0, provider.update_interval.total_seconds())
                        ),
                        fx_rate=(mid * Decimal(str(1 - m))).quantize(Decimal("0.0001")),
                        fee_flat=Decimal(flat),
                        fee_pct=Decimal(pct),
                        transfer_time=timedelta(minutes=minutes) if minutes else None,
                        source=SAMPLE,
                    )
                )
        ProviderQuote.objects.bulk_create(rows, ignore_conflicts=True)
        return len(rows)
