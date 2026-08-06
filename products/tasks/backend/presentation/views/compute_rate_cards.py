from typing import Any

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.tasks.backend.facade import compute_rates

logger = structlog.get_logger(__name__)


class ComputeRateCardSerializer(serializers.Serializer):
    version = serializers.CharField(help_text="Published compute rate-card version.")
    effective_at = serializers.DateTimeField(help_text="Timestamp when this rate card became effective.")
    expires_at = serializers.DateTimeField(
        allow_null=True, help_text="Timestamp when this rate card stopped applying, or null for the current version."
    )
    cpu_usd_per_core_second = serializers.DecimalField(
        max_digits=24,
        decimal_places=18,
        normalize_output=True,
        help_text="Published USD price per CPU core-second.",
    )
    memory_usd_per_gib_second = serializers.DecimalField(
        max_digits=24,
        decimal_places=18,
        normalize_output=True,
        help_text="Published USD price per memory GiB-second.",
    )


class ComputeRateCardsResponseSerializer(serializers.Serializer):
    rate_cards = ComputeRateCardSerializer(
        many=True,
        allow_null=True,
        help_text=(
            "Published compute rate cards overlapping the organization's synchronized billing period. "
            "Null means the configured rate cards are invalid; an empty list means compute pricing is inactive."
        ),
    )
    error = serializers.ChoiceField(
        choices=("invalid_configuration",),
        allow_null=True,
        help_text="Set when configured compute rates are invalid and therefore omitted.",
    )


@extend_schema(tags=["tasks"])
class ComputeRateCardsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "project"
    required_scopes = ["project:read"]
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        summary="Get published cloud-compute rates",
        responses={200: ComputeRateCardsResponseSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        rates = compute_rates.get_published_compute_rates((self.team.organization.usage or {}).get("period"))
        if rates.error:
            logger.error("posthog_code_compute_rate_card_invalid")
        return Response(ComputeRateCardsResponseSerializer({"rate_cards": rates.rate_cards, "error": rates.error}).data)
