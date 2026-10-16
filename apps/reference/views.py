from rest_framework import viewsets

from .models import Corridor, Country, Currency, Provider
from .serializers import (
    CorridorSerializer,
    CountrySerializer,
    CurrencySerializer,
    ProviderSerializer,
)


class CurrencyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Currency.objects.all()
    serializer_class = CurrencySerializer
    pagination_class = None


class CountryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Country.objects.filter(is_active=True)
    serializer_class = CountrySerializer
    pagination_class = None

    def get_queryset(self):
        """Optional ``?role=sending|receiving`` filter."""
        qs = super().get_queryset()
        role = self.request.query_params.get("role")
        if role == "sending":
            qs = qs.filter(is_sending=True)
        elif role == "receiving":
            qs = qs.filter(is_receiving=True)
        return qs


class CorridorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Corridor.objects.filter(is_active=True)
    serializer_class = CorridorSerializer
    pagination_class = None


class ProviderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Provider.objects.filter(is_active=True).prefetch_related("corridors")
    serializer_class = ProviderSerializer
    lookup_field = "slug"
    pagination_class = None
