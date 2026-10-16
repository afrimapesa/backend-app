from rest_framework.routers import DefaultRouter

from .views import CorridorViewSet, CountryViewSet, CurrencyViewSet, ProviderViewSet

router = DefaultRouter()
router.register("currencies", CurrencyViewSet)
router.register("countries", CountryViewSet)
router.register("corridors", CorridorViewSet)
router.register("providers", ProviderViewSet)

urlpatterns = router.urls
