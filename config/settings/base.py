"""Settings shared by every environment. Values come from the environment / .env file."""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    # Local
    "apps.core",
    "apps.reference",
    "apps.ingestion",
    "apps.fx",
    "apps.remittance",
    "apps.insights",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# PostgreSQL + TimescaleDB, e.g. postgres://user:pass@localhost:5432/afrimapesa
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AfrimaPesa API",
    "DESCRIPTION": "Cross-border financial comparison and intelligence for Africa.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# Celery: scheduled ingestion (FX every 5 min, provider scrapers hourly)
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# --- Mid-market FX feeds (strategy doc §3.1; plan T07) ------------------------------------
# Each feed runs only when its key is set. Free plans allow roughly 1,000-1,500 calls a
# month, so the default refresh is hourly; set FX_REFRESH_MINUTES=5 on a paid plan.
OPEN_EXCHANGE_RATES_APP_ID = env("OPEN_EXCHANGE_RATES_APP_ID", default="")
EXCHANGE_RATE_API_KEY = env("EXCHANGE_RATE_API_KEY", default="")
EXCHANGE_RATE_API_BASE = env("EXCHANGE_RATE_API_BASE", default="EUR")
CURRENCY_FREAKS_API_KEY = env("CURRENCY_FREAKS_API_KEY", default="")
CURRENCY_FREAKS_BASE = env("CURRENCY_FREAKS_BASE", default="GBP")
FX_REFRESH_MINUTES = env.int("FX_REFRESH_MINUTES", default=60)
# Older mid rates are not used for comparisons. Keep it above the refresh interval plus
# the feed's own update lag (hourly free plans: 150).
FX_MID_MAX_AGE = timedelta(minutes=env.int("FX_MID_MAX_AGE_MINUTES", default=30))

_FX_FEEDS = {
    "openexchangerates": OPEN_EXCHANGE_RATES_APP_ID,
    "exchangerate_api": EXCHANGE_RATE_API_KEY,
    "currencyfreaks": CURRENCY_FREAKS_API_KEY,
}
CELERY_BEAT_SCHEDULE: dict = {
    f"fx-{source}": {
        "task": "ingestion.run_adapter",
        "schedule": timedelta(minutes=FX_REFRESH_MINUTES),
        "args": (source,),
    }
    for source, key in _FX_FEEDS.items()
    if key
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
