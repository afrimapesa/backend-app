from django.urls import path

from .views import CompareView

urlpatterns = [
    path("compare/", CompareView.as_view(), name="remittance-compare"),
]
