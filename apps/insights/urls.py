from django.urls import path

from .views import ArticleDetailView, ArticleListView, FrontPageView

urlpatterns = [
    path("front/", FrontPageView.as_view(), name="insights-front"),
    path("articles/", ArticleListView.as_view(), name="insights-articles"),
    path("articles/<slug:slug>/", ArticleDetailView.as_view(), name="insights-article"),
]
