from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reference.models import Currency

from .history import daily_history


class HistoryQuerySerializer(serializers.Serializer):
    base = serializers.CharField(min_length=3, max_length=3)
    quote = serializers.CharField(min_length=3, max_length=3)
    days = serializers.IntegerField(min_value=1, max_value=365, default=90)

    def validate(self, attrs):
        attrs["base"], attrs["quote"] = attrs["base"].upper(), attrs["quote"].upper()
        known = set(
            Currency.objects.filter(code__in=[attrs["base"], attrs["quote"]]).values_list(
                "code", flat=True
            )
        )
        for field in ("base", "quote"):
            if attrs[field] not in known:
                raise serializers.ValidationError({field: f"Unknown currency {attrs[field]}"})
        if attrs["base"] == attrs["quote"]:
            raise serializers.ValidationError("base and quote must differ")
        return attrs


class HistoryPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    rate = serializers.DecimalField(max_digits=24, decimal_places=10)


class HistoryResponseSerializer(serializers.Serializer):
    base = serializers.CharField()
    quote = serializers.CharField()
    days = serializers.IntegerField()
    derived = serializers.BooleanField(help_text="True when computed as a cross rate via USD.")
    points = HistoryPointSerializer(many=True)


class FxHistoryView(APIView):
    """Daily mid-market rate for a currency pair (last observation of each UTC day)."""

    @extend_schema(
        parameters=[
            OpenApiParameter("base", str, required=True, description="e.g. GBP"),
            OpenApiParameter("quote", str, required=True, description="e.g. NGN"),
            OpenApiParameter("days", int, description="1-365, default 90"),
        ],
        responses=HistoryResponseSerializer,
    )
    def get(self, request: Request) -> Response:
        query = HistoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        base, quote, days = (query.validated_data[k] for k in ("base", "quote", "days"))

        series = daily_history(base, quote, days=days, today=timezone.now().date())
        body = HistoryResponseSerializer(
            {
                "base": base,
                "quote": quote,
                "days": days,
                "derived": series.derived,
                "points": [{"date": d, "rate": r} for d, r in series.points],
            }
        )
        return Response(body.data)
