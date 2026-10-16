from django.contrib import admin

from .models import Corridor, Country, Currency, Provider, UserPreference


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "symbol", "minor_units"]
    search_fields = ["code", "name"]


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "kind", "currency", "is_sending", "is_receiving", "is_active"]
    list_filter = ["is_sending", "is_receiving", "is_active"]
    search_fields = ["code", "name"]


@admin.register(Corridor)
class CorridorAdmin(admin.ModelAdmin):
    list_display = ["__str__", "send_country", "receive_country", "is_active"]
    list_filter = ["send_country", "receive_country", "is_active"]


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "integration_method", "update_interval", "is_active"]
    list_filter = ["integration_method", "is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}
    filter_horizontal = ["corridors"]


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "focus_country", "send_country", "updated_at"]
    raw_id_fields = ["user"]
