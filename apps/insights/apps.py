from django.apps import AppConfig


class InsightsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.insights"
    verbose_name = "News & insights"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (connects front-page cache invalidation)
