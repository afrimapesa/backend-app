from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reference.models import Corridor, Country

from .compare import compare

MAX_AMOUNT = Decimal("1000000")


class CompareQuerySerializer(serializers.Serializer):
    send = serializers.CharField(min_length=2, max_length=2, help_text="Sending country, e.g. GB")
    receive = serializers.CharField(min_length=2, max_length=2, help_text="Receiving, e.g. NG")
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), max_value=MAX_AMOUNT
    )


class ProviderSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    website = serializers.URLField()


class QuoteResultSerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    provider = ProviderSerializer()
    fx_rate = serializers.DecimalField(max_digits=24, decimal_places=10)
    transfer_fee = serializers.DecimalField(max_digits=14, decimal_places=2)
    margin_cost = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text="Cost hidden in the rate, sending currency."
    )
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_cost_pct = serializers.DecimalField(max_digits=10, decimal_places=6)
    net_payout = serializers.DecimalField(max_digits=20, decimal_places=2)
    effective_rate = serializers.DecimalField(max_digits=24, decimal_places=6)
    transfer_time_minutes = serializers.IntegerField(allow_null=True)
    observed_at = serializers.DateTimeField()
    is_stale = serializers.BooleanField()


class CompareResponseSerializer(serializers.Serializer):
    as_of = serializers.DateTimeField(help_text="Server time the comparison was made.")
    corridor = serializers.CharField()
    send_currency = serializers.CharField()
    receive_currency = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    mid_rate = serializers.DecimalField(max_digits=24, decimal_places=10, allow_null=True)
    mid_payout = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    mid_observed_at = serializers.DateTimeField(allow_null=True)
    providers_on_route = serializers.IntegerField()
    sample = serializers.BooleanField(help_text="True when any figure is preview sample data.")
    results = QuoteResultSerializer(many=True)


class CompareView(APIView):
    """Top 5 providers for a corridor and amount, ranked by what the recipient receives.

    Neutral by design: results are ordered by amount received (fresh quotes before stale
    ones); no provider is recommended.
    """

    @extend_schema(
        parameters=[
            OpenApiParameter("send", str, required=True, description="Sending country, e.g. GB"),
            OpenApiParameter("receive", str, required=True, description="Receiving, e.g. NG"),
            OpenApiParameter("amount", str, required=True, description="Amount to send, e.g. 200"),
        ],
        responses=CompareResponseSerializer,
    )
    def get(self, request: Request) -> Response:
        query = CompareQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        # Euro-area countries are priced with the EU corridors (Country.pricing_market).
        sender = get_object_or_404(
            Country, code=query.validated_data["send"].upper(), is_sending=True, is_active=True
        )
        corridor = get_object_or_404(
            Corridor.objects.select_related("send_currency", "receive_currency"),
            send_country=sender.corridor_country_id,
            receive_country=query.validated_data["receive"].upper(),
            is_active=True,
        )

        now = timezone.now()
        result = compare(corridor, query.validated_data["amount"], now=now)
        snap = result.snapshot
        body = CompareResponseSerializer(
            {
                "as_of": now,
                "corridor": snap.corridor_code,
                "send_currency": snap.send_currency,
                "receive_currency": snap.receive_currency,
                "amount": result.amount,
                "mid_rate": snap.mid.rate if snap.mid else None,
                "mid_payout": result.mid_payout,
                "mid_observed_at": snap.mid.observed_at if snap.mid else None,
                "providers_on_route": snap.providers_on_route,
                "sample": result.sample,
                "results": [
                    {
                        "rank": r.rank,
                        "provider": snap.providers[r.provider],
                        "fx_rate": r.fx_rate,
                        "transfer_fee": r.transfer_fee,
                        "margin_cost": max(Decimal(0), r.total_cost - r.transfer_fee),
                        "total_cost": r.total_cost,
                        "total_cost_pct": r.total_cost_pct,
                        "net_payout": r.net_payout,
                        "effective_rate": r.effective_rate,
                        "transfer_time_minutes": (
                            int(r.transfer_time.total_seconds() // 60)
                            if r.transfer_time is not None
                            else None
                        ),
                        "observed_at": r.observed_at,
                        "is_stale": r.is_stale,
                    }
                    for r in result.results
                ],
            }
        )
        return Response(body.data)
