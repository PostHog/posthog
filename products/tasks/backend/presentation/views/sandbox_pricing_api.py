from dataclasses import asdict

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from products.tasks.backend.facade.pricing import get_compute_rate_card_catalog


class ComputeRateCardSerializer(serializers.Serializer):
    version = serializers.CharField(help_text="Stable identifier for this rate card.")
    effective_at = serializers.DateTimeField(help_text="Time when this rate card became effective.")
    expires_at = serializers.DateTimeField(
        allow_null=True,
        help_text="Time when this rate card stopped applying, or null while it remains current.",
    )
    cpu_core_second_usd = serializers.CharField(help_text="USD charged per CPU core-second as an exact decimal string.")
    memory_gib_second_usd = serializers.CharField(
        help_text="USD charged per GiB-second of memory as an exact decimal string."
    )


@extend_schema_serializer(many=False)
class SandboxComputePricingSerializer(serializers.Serializer):
    current = ComputeRateCardSerializer(
        allow_null=True,
        help_text="Currently effective sandbox compute rate card, or null before pricing is published.",
    )
    history = ComputeRateCardSerializer(
        many=True,
        help_text="Expired sandbox compute rate cards, newest first.",
    )


class SandboxComputePricingViewSet(viewsets.ViewSet):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes: list[type] = []
    scope_object = None
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        responses={200: SandboxComputePricingSerializer},
        summary="Get sandbox compute pricing",
        description="Get the current sandbox compute rate card and expired rate-card history.",
    )
    def list(self, request: Request) -> Response:
        catalog = get_compute_rate_card_catalog()
        payload = {
            "current": asdict(catalog.current) if catalog.current is not None else None,
            "history": [asdict(card) for card in catalog.history],
        }
        return Response(SandboxComputePricingSerializer(payload).data)
