from django.contrib import admin

from .models import IngestionRun


@admin.register(IngestionRun)
class IngestionRunAdmin(admin.ModelAdmin):
    list_display = [
        "source",
        "status",
        "started_at",
        "finished_at",
        "records_fetched",
        "records_stored",
        "records_rejected",
    ]
    list_filter = ["status", "source"]
    date_hierarchy = "started_at"

    # Runs are written by adapters only; the admin is a read-only log.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
