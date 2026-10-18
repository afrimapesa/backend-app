# AfrimaPesa Backend

Django REST Framework API for AfrimaPesa: remittance cost comparison, commercial banking rates and sovereign yields for NG, GH, KE, TZ, EG and ZA. Project context lives in [docs/](docs/).

**Stack:** Python 3.13, Django 5.2, DRF, PostgreSQL 16 + TimescaleDB, Redis, Celery.

## Local setup

```bash
# 1. Services (Postgres/TimescaleDB + Redis)
docker compose up -d

# 2. Python env
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements/dev.txt

# 3. Config
cp .env.example .env            # then set DJANGO_SECRET_KEY

# 4. Database + run
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

- Health check: http://localhost:8000/health/
- API docs (Swagger): http://localhost:8000/v1/docs/
- Django admin: http://localhost:8000/admin/

Celery worker / beat (for scheduled ingestion):

```bash
celery -A config worker -l info --pool=solo   # --pool=solo needed on Windows
celery -A config beat -l info
```

Or run the whole stack in containers: `docker compose --profile app up --build`.

## Historical FX rates

Load past mid-market rates (for the trend chart) from a CSV or Excel file:

```bash
python manage.py import_fx_history rates.xlsx --dry-run   # check what will be read
python manage.py import_fx_history rates.xlsx
```

Accepted layouts: long (`date, base, quote, rate`, or `date, pair, rate` with pairs like
`USD/NGN`) or wide (a `date` column plus one column per pair, headed `USD/NGN`). Dates
like `2026-10-01` or `01/10/2026`. Re-importing is safe; existing days are kept.
The data is served at `GET /v1/fx/history/?base=GBP&quote=NGN&days=90`.

## Quality checks

```bash
ruff check . && ruff format --check .
mypy .
pytest --cov
```

CI runs the same checks on every push and pull request (`.github/workflows/ci.yml`).

## Layout

```
config/            settings (base/dev/test/prod), urls, celery
apps/core/         shared utilities, health endpoint
apps/reference/    currencies, countries, 18 corridors, 15 providers (seeded) — /v1/reference/
apps/fx/           mid-market rates, history endpoint, import_fx_history command
apps/remittance/   calculation engine (engine.py): fees, A_net, effective rate, top-5 ranking
```
