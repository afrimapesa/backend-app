from rest_framework import serializers

from .models import Advertisement, Article, Author


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = ["slug", "name", "role"]


class SectionField(serializers.Field):
    def to_representation(self, value: str) -> dict:
        return {"key": value, "label": Article.Section(value).label}


class ArticleCardSerializer(serializers.ModelSerializer):
    """What a headline needs on a listing: no body."""

    section = SectionField()
    kind_label = serializers.CharField(source="get_kind_display")
    countries = serializers.SlugRelatedField(slug_field="code", many=True, read_only=True)
    currency = serializers.CharField(source="currency_id", allow_null=True)
    author = AuthorSerializer(allow_null=True)
    reading_minutes = serializers.IntegerField()

    class Meta:
        model = Article
        fields = [
            "slug",
            "title",
            "standfirst",
            "kind",
            "kind_label",
            "section",
            "countries",
            "currency",
            "author",
            "cover_image_url",
            "cover_credit",
            "published_at",
            "updated_at",
            "reading_minutes",
            "is_featured",
            "sample",
        ]


class ArticleDetailSerializer(ArticleCardSerializer):
    class Meta(ArticleCardSerializer.Meta):
        fields = [*ArticleCardSerializer.Meta.fields, "body"]


class AdvertisementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Advertisement
        fields = ["advertiser", "placement", "image_url", "click_url", "alt_text"]
