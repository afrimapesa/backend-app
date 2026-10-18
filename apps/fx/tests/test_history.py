from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse
from openpyxl import Workbook

from apps.fx.history import daily_history, parse_rates
from apps.fx.models import FxMidRate
from apps.ingestion.models import IngestionRun

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 18)


def at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def add(base, quote, rate, when):
    FxMidRate.objects.create(
        base_id=base, quote_id=quote, rate=D(rate), observed_at=when, source="manual"
    )


class TestDailyHistory:
    def test_last_observation_of_each_day(self):
        d1, d2 = TODAY - timedelta(days=1), TODAY
        add("GBP", "NGN", "2030", at(d1, 9))
        add("GBP", "NGN", "2035", at(d1, 18))  # later the same day wins
        add("GBP", "NGN", "2040", at(d2, 10))

        series = daily_history("GBP", "NGN", days=7, today=TODAY)
        assert series.points == [(d1, D("2035")), (d2, D("2040"))]
        assert series.derived is False

    def test_window_excludes_older_days(self):
        add("GBP", "NGN", "1999", at(TODAY - timedelta(days=10)))
        add("GBP", "NGN", "2040", at(TODAY))
        series = daily_history("GBP", "NGN", days=7, today=TODAY)
        assert [d for d, _ in series.points] == [TODAY]

    def test_cross_rate_via_usd_on_shared_days(self):
        d1, d2 = TODAY - timedelta(days=1), TODAY
        add("USD", "NGN", "1530", at(d1))
        add("USD", "KES", "129.2", at(d1))
        add("USD", "NGN", "1531", at(d2))  # no KES leg on d2 -> no point

        series = daily_history("NGN", "KES", days=7, today=TODAY)
        assert series.derived is True
        assert series.points == [(d1, D("129.2") / D("1530"))]

    def test_empty(self):
        series = daily_history("GBP", "ZAR", days=90, today=TODAY)
        assert series.points == []
        assert series.derived is False


class TestHistoryEndpoint:
    def test_returns_points(self, client):
        add("GBP", "NGN", "2040.5", datetime.now(UTC))
        response = client.get(reverse("fx-history"), {"base": "gbp", "quote": "NGN", "days": 30})
        assert response.status_code == 200
        body = response.json()
        assert (body["base"], body["quote"], body["days"], body["derived"]) == (
            "GBP",
            "NGN",
            30,
            False,
        )
        assert len(body["points"]) == 1
        assert D(body["points"][0]["rate"]) == D("2040.5")

    @pytest.mark.parametrize(
        "params",
        [
            {"base": "GBP"},  # missing quote
            {"base": "GBP", "quote": "XYZ"},
            {"base": "GBP", "quote": "GBP"},
            {"base": "GBP", "quote": "NGN", "days": 0},
            {"base": "GBP", "quote": "NGN", "days": 400},
        ],
    )
    def test_rejects_bad_params(self, client, params):
        assert client.get(reverse("fx-history"), params).status_code == 400


class TestParseRates:
    def test_long_format(self):
        rows = [
            ["Date", "Base", "Quote", "Rate"],
            ["2026-10-01", "usd", "ngn", "1,530.25"],
            ["02/10/2026", "USD", "NGN", "1531"],
        ]
        parsed = list(parse_rates(rows))
        assert [(r.day, r.base, r.quote, r.rate) for r in parsed] == [
            (date(2026, 10, 1), "USD", "NGN", D("1530.25")),
            (date(2026, 10, 2), "USD", "NGN", D("1531")),
        ]

    def test_long_format_with_pair_column(self):
        parsed = list(parse_rates([["date", "pair", "rate"], ["2026-10-01", "GBP/KES", 172.3]]))
        assert (parsed[0].base, parsed[0].quote) == ("GBP", "KES")

    def test_wide_format_skips_blanks_and_reports_bad_cells(self):
        rows = [
            ["Date", "USD/NGN", "USDKES", "notes"],
            [datetime(2026, 10, 1), 1530, 129.2, None],
            [datetime(2026, 10, 2), None, "n/a", None],
        ]
        parsed = list(parse_rates(rows))
        rates = [p for p in parsed if not isinstance(p, str)]
        problems = [p for p in parsed if isinstance(p, str)]
        assert [(r.day, r.base, r.quote) for r in rates] == [
            (date(2026, 10, 1), "USD", "NGN"),
            (date(2026, 10, 1), "USD", "KES"),
        ]
        assert any("notes" in p for p in problems)
        assert any("n/a" in p for p in problems)

    @pytest.mark.parametrize(
        "rows",
        [
            [["day", "rate"], ["2026-10-01", 1]],  # no date column
            [["date", "rate"], ["2026-10-01", 1]],  # long format without pair info
            [["date", "notes"], ["2026-10-01", "x"]],  # wide format without pairs
        ],
    )
    def test_unreadable_layouts(self, rows):
        with pytest.raises(ValueError):
            list(parse_rates(rows))


class TestImportCommand:
    def test_imports_csv_and_logs_run(self, tmp_path):
        f = tmp_path / "rates.csv"
        f.write_text("date,USD/NGN,USD/XYZ\n2026-10-01,1530,1\n2026-10-02,1531,1\n")
        out = StringIO()
        call_command("import_fx_history", str(f), stdout=out)

        assert FxMidRate.objects.filter(base="USD", quote="NGN", source="import").count() == 2
        run = IngestionRun.objects.get(source="fx_history_import")
        assert run.status == IngestionRun.Status.PARTIAL  # XYZ is unknown
        assert run.records_stored == 2
        assert "Saved 2 new rates" in out.getvalue()

    def test_reimport_is_idempotent(self, tmp_path):
        f = tmp_path / "rates.csv"
        f.write_text("date,base,quote,rate\n2026-10-01,GBP,NGN,2040\n")
        call_command("import_fx_history", str(f), stdout=StringIO())
        out = StringIO()
        call_command("import_fx_history", str(f), stdout=out)
        assert FxMidRate.objects.count() == 1
        assert "Saved 0 new rates (1 already present)" in out.getvalue()

    def test_imports_xlsx(self, tmp_path):
        wb = Workbook()
        wb.active.append(["Date", "EUR/GHS"])
        wb.active.append([datetime(2026, 10, 1), 17.9])
        f = tmp_path / "rates.xlsx"
        wb.save(f)
        call_command("import_fx_history", str(f), stdout=StringIO())
        assert FxMidRate.objects.get(base="EUR", quote="GHS").rate == D("17.9")

    def test_dry_run_saves_nothing(self, tmp_path):
        f = tmp_path / "rates.csv"
        f.write_text("date,base,quote,rate\n2026-10-01,GBP,NGN,2040\n")
        out = StringIO()
        call_command("import_fx_history", str(f), "--dry-run", stdout=out)
        assert FxMidRate.objects.count() == 0
        assert "Dry run" in out.getvalue()

    def test_missing_file(self, tmp_path):
        with pytest.raises(CommandError, match="not found"):
            call_command("import_fx_history", str(tmp_path / "nope.csv"))

    def test_unsupported_type(self, tmp_path):
        f = tmp_path / "rates.json"
        f.write_text("{}")
        with pytest.raises(CommandError, match="Unsupported"):
            call_command("import_fx_history", str(f))
