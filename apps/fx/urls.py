from django.urls import path

from .views import FxHistoryView, FxMoversView

urlpatterns = [
    path("history/", FxHistoryView.as_view(), name="fx-history"),
    path("movers/", FxMoversView.as_view(), name="fx-movers"),
]
