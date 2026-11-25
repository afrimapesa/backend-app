from django.apps import AppConfig


class FxConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fx"

    def ready(self) -> None:
        # Register the live FX feeds so Celery beat can run them by source name.
        from . import feeds  # noqa: F401
