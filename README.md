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

## Comparison API and sample data

`GET /v1/remittance/compare/?send=GB&receive=NG&amount=200` returns the top 5 providers for a
corridor, ranked by what the recipient receives (fresh quotes before stale ones; every quote
carries `is_stale`). The latest quotes and mid-market rate per corridor are cached in Redis
for 60 s and dropped whenever an adapter stores new quotes.

Until live feeds run, fill the database with **labelled sample data** (responses then carry
`"sample": true` and the site says so):

```bash
python manage.py seed_sample_quotes              # one fresh set (+90 days of rate history)
python manage.py seed_sample_quotes --loop 300   # keep it fresh; mid rates expire after 30 min
python manage.py seed_sample_quotes --clear      # remove all sample data
```

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

## News & insights

Articles, bylines and advertisements are managed in the Django admin (**News & insights**).
Nothing is syndicated: wire stories would need a Reuters/Bloomberg licence (plan D05).
Article bodies are plain text: paragraphs separated by a blank line, `## ` for subheadings.

- `GET /v1/insights/front/`: the whole front page (lead, top stories, latest, sections,
  opinion & analysis, explainers, booked ads per slot), cached 60 s and dropped on any edit.
- `GET /v1/insights/articles/?section=currencies&kind=analysis&country=NG&page=2`
- `GET /v1/insights/articles/<slug>/`: body plus related stories.
- `GET /v1/fx/movers/?base=USD&days=30`: each receiving currency's latest rate, 1-day and
  period change, and daily points (for the markets band).

Ad slots: `leaderboard` (970×90), `rail` (300×250), `inline` (728×90, inside articles). Ads
are always labelled and never appear inside comparison results.

```bash
python manage.py seed_sample_articles          # labelled sample articles for the preview
python manage.py seed_sample_articles --clear  # remove them
```

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
apps/reference/    currencies, countries, 18 corridors, 15 providers (seeded) â€” /v1/reference/
apps/fx/           mid-market rates, history endpoint, import_fx_history command
apps/remittance/   calculation engine (engine.py): fees, A_net, effective rate, top-5 ranking
apps/insights/     news & insights: articles, authors, ad slots, cached front page
```
