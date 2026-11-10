from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reference.models import Currency

from .history import daily_history
from .movers import movers


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
    sample = serializers.BooleanField(help_text="True when any point is preview sample data.")
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
                "sample": series.sample,
                "points": [{"date": d, "rate": r} for d, r in series.points],
            }
        )
        return Response(body.data)


class MoversQuerySerializer(serializers.Serializer):
    base = serializers.CharField(min_length=3, max_length=3, default="USD")
    days = serializers.IntegerField(min_value=2, max_value=365, default=30)

    def validate_base(self, value: str) -> str:
        value = value.upper()
        if not Currency.objects.filter(code=value).exists():
            raise serializers.ValidationError(f"Unknown currency {value}")
        return value


class MoverSerializer(serializers.Serializer):
    currency = serializers.CharField()
    name = serializers.CharField()
    country = serializers.CharField()
    rate = serializers.DecimalField(max_digits=24, decimal_places=10)
    change_1d = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        allow_null=True,
        help_text="Fractional change in the rate since the previous day (0.01 = +1%).",
    )
    change_period = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        allow_null=True,
        help_text="Fractional change in the rate over the whole period.",
    )
    sample = serializers.BooleanField()
    points = HistoryPointSerializer(many=True)


class MoversResponseSerializer(serializers.Serializer):
    base = serializers.CharField()
    days = serializers.IntegerField()
    sample = serializers.BooleanField()
    movers = MoverSerializer(many=True)


class FxMoversView(APIView):
    """Each receiving-country currency against ``base``: latest rate, changes and daily points.

    A rising rate means the African currency buys less of ``base`` (it weakened).
    """

    @extend_schema(
        parameters=[
            OpenApiParameter("base", str, description="default USD"),
            OpenApiParameter("days", int, description="2-365, default 30"),
        ],
        responses=MoversResponseSerializer,
    )
    def get(self, request: Request) -> Response:
        query = MoversQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        base, days = query.validated_data["base"], query.validated_data["days"]
        items = movers(base, days=days, today=timezone.now().date())
        body = MoversResponseSerializer(
            {
                "base": base,
                "days": days,
                "sample": any(m.sample for m in items),
                "movers": [
                    {
                        **m.__dict__,
                        "points": [{"date": d, "rate": r} for d, r in m.points],
                    }
                    for m in items
                ],
            }
        )
        return Response(body.data)
