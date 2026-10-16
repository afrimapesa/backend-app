from rest_framework import serializers

from .models import Corridor, Country, Currency, Provider


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ["code", "name", "symbol", "minor_units"]


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = [
            "code",
            "name",
            "kind",
            "currency",
            "is_sending",
            "is_receiving",
            "central_bank",
            "central_bank_code",
        ]


class CorridorSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)

    class Meta:
        model = Corridor
        fields = ["code", "send_country", "send_currency", "receive_country", "receive_currency"]


class ProviderSerializer(serializers.ModelSerializer):
    corridors = serializers.SerializerMethodField()

    class Meta:
        model = Provider
        fields = ["slug", "name", "website", "integration_method", "update_interval", "corridors"]

    def get_corridors(self, obj: Provider) -> list[str]:
        return [c.code for c in obj.corridors.all()]
