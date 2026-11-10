from django.contrib import admin

from .models import Advertisement, Article, Author


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ["name", "role"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["title", "section", "kind", "status", "is_featured", "published_at", "sample"]
    list_filter = ["status", "section", "kind", "is_featured", "sample"]
    list_editable = ["status", "is_featured"]
    search_fields = ["title", "standfirst", "body"]
    prepopulated_fields = {"slug": ["title"]}
    filter_horizontal = ["countries"]
    autocomplete_fields = ["author"]
    date_hierarchy = "published_at"
    fieldsets = [
        (None, {"fields": ["title", "slug", "standfirst", "body"]}),
        ("Placement", {"fields": ["section", "kind", "countries", "currency", "is_featured"]}),
        ("Byline & cover", {"fields": ["author", "cover_image_url", "cover_credit"]}),
        ("Publishing", {"fields": ["status", "published_at", "sample"]}),
    ]


@admin.register(Advertisement)
class AdvertisementAdmin(admin.ModelAdmin):
    list_display = ["name", "advertiser", "placement", "starts_at", "ends_at", "is_active"]
    list_filter = ["placement", "is_active"]
    search_fields = ["name", "advertiser"]
