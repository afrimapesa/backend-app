"""Load historical mid-market rates from a CSV or Excel file into fx_mid_rates.

    python manage.py import_fx_history rates.xlsx [--dry-run]

See apps.fx.history.parse_rates for the accepted layouts. Re-importing the same file is
safe: a (base, quote, day) already stored is left untouched.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.fx.history import HistoricalRate, ImportFormatError, parse_rates, read_rows
from apps.fx.models import FxMidRate
from apps.ingestion.models import IngestionRun
from apps.reference.models import Currency

MAX_SHOWN_PROBLEMS = 20


class Command(BaseCommand):
    help = "Import historical mid-market FX rates from a .csv or .xlsx file."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument(
            "--dry-run", action="store_true", help="Parse and validate without saving."
        )

    def handle(self, *args, path: Path, dry_run: bool, **options):
        if not path.exists():
            raise CommandError(f"File not found: {path}")
        try:
            parsed = list(parse_rates(read_rows(path)))
        except ImportFormatError as exc:
            raise CommandError(str(exc)) from exc

        known = set(Currency.objects.values_list("code", flat=True))
        rates: list[HistoricalRate] = []
        problems: list[str] = []
        for item in parsed:
            if isinstance(item, str):
                problems.append(item)
            elif item.base not in known or item.quote not in known:
                problems.append(f"{item.day} {item.base}/{item.quote}: unknown currency")
            elif item.base == item.quote:
                problems.append(f"{item.day} {item.base}/{item.quote}: same currency")
            else:
                rates.append(item)

        pairs = sorted({f"{r.base}/{r.quote}" for r in rates})
        days = sorted({r.day for r in rates})
        self.stdout.write(
            f"Parsed {len(rates)} rates for {len(pairs)} pairs ({', '.join(pairs)})"
            + (f" from {days[0]} to {days[-1]}" if days else "")
        )
        for problem in problems[:MAX_SHOWN_PROBLEMS]:
            self.stdout.write(self.style.WARNING(f"  skipped {problem}"))
        if len(problems) > MAX_SHOWN_PROBLEMS:
            self.stdout.write(
                self.style.WARNING(f"  ...and {len(problems) - MAX_SHOWN_PROBLEMS} more")
            )

        if dry_run or not rates:
            self.stdout.write("Dry run: nothing saved." if dry_run else "Nothing to save.")
            return

        run = IngestionRun.objects.create(source="fx_history_import")
        with transaction.atomic():
            before = FxMidRate.objects.count()
            FxMidRate.objects.bulk_create(
                [
                    FxMidRate(
                        base_id=r.base,
                        quote_id=r.quote,
                        observed_at=r.observed_at,
                        rate=r.rate,
                        source=FxMidRate.Source.IMPORT,
                        ingestion_run=run,
                    )
                    for r in rates
                ],
                ignore_conflicts=True,
                batch_size=1000,
            )
            stored = FxMidRate.objects.count() - before

        run.records_fetched = len(parsed)
        run.records_stored = stored
        run.records_rejected = len(problems)
        run.status = IngestionRun.Status.PARTIAL if problems else IngestionRun.Status.SUCCESS
        run.details = {"file": path.name, "pairs": pairs, "problems": problems[:50]}
        run.finished_at = timezone.now()
        run.save()
        self.stdout.write(
            self.style.SUCCESS(f"Saved {stored} new rates ({len(rates) - stored} already present).")
        )
