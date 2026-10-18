from django.urls import path

from .views import FxHistoryView

urlpatterns = [
    path("history/", FxHistoryView.as_view(), name="fx-history"),
]
