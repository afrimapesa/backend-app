from .base import *  # noqa: F403

DEBUG = False

# Behind Caddy, which terminates HTTPS and redirects HTTP itself. Django must not redirect:
# the frontend container calls the API over the internal Docker network on plain HTTP.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 30)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = False  # the root domain may be hosted elsewhere
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# WhiteNoise serves /static/ (admin and API docs CSS) straight from gunicorn.
MIDDLEWARE.insert(  # noqa: F405
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Intentional for this deployment (see `manage.py check --deploy`):
# W008 Caddy redirects HTTP to HTTPS, not Django; W005/W021 HSTS subdomains/preload stay
# off while the root domain may be served elsewhere.
SILENCED_SYSTEM_CHECKS = ["security.W008", "security.W005", "security.W021"]
