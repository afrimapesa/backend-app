from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import front
from .models import Article
from .serializers import ArticleCardSerializer, ArticleDetailSerializer

RELATED_COUNT = 4


class FrontPageView(APIView):
    """Everything the news front page shows, in one cached response."""

    @extend_schema(
        responses=inline_serializer(
            "InsightsFrontPage",
            {
                "as_of": serializers.DateTimeField(),
                "sample": serializers.BooleanField(),
                "lead": ArticleCardSerializer(allow_null=True),
                "top": ArticleCardSerializer(many=True),
                "latest": ArticleCardSerializer(many=True),
                "sections": serializers.ListField(child=serializers.DictField()),
                "commentary": ArticleCardSerializer(many=True),
                "explainers": ArticleCardSerializer(many=True),
                "ads": serializers.DictField(),
            },
        )
    )
    def get(self, request: Request) -> Response:
        now = timezone.now()
        return Response({"as_of": now, **front.front_page(now=now)})


class ArticlePagination(PageNumberPagination):
    page_size = 20
    max_page_size = 50
    page_size_query_param = "page_size"


class ArticleListView(generics.ListAPIView):
    """Published articles, newest first, filterable by section, kind and country."""

    serializer_class = ArticleCardSerializer
    pagination_class = ArticlePagination

    @extend_schema(
        parameters=[
            OpenApiParameter("section", str, enum=Article.Section.values),
            OpenApiParameter("kind", str, enum=Article.Kind.values),
            OpenApiParameter("country", str, description="ISO code, e.g. NG"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = Article.objects.live().select_related("author").prefetch_related("countries")
        params = self.request.query_params
        if section := params.get("section"):
            qs = qs.filter(section=section)
        if kind := params.get("kind"):
            qs = qs.filter(kind=kind)
        if country := params.get("country"):
            qs = qs.filter(countries__code=country.upper())
        return qs


class ArticleDetailView(APIView):
    """One published article with its body, plus related stories from the same section."""

    @extend_schema(
        responses=inline_serializer(
            "InsightsArticle",
            {
                "as_of": serializers.DateTimeField(),
                "article": ArticleDetailSerializer(),
                "related": ArticleCardSerializer(many=True),
            },
        )
    )
    def get(self, request: Request, slug: str) -> Response:
        now = timezone.now()
        live = Article.objects.live(now).select_related("author").prefetch_related("countries")
        article = get_object_or_404(live, slug=slug)
        related = live.filter(section=article.section).exclude(pk=article.pk)[:RELATED_COUNT]
        return Response(
            {
                "as_of": now,
                "article": ArticleDetailSerializer(article).data,
                "related": ArticleCardSerializer(related, many=True).data,
            }
        )
