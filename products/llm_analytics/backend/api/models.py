from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import AccessControlPermission

from ..llm import TRIAL_MODELS_BY_PROVIDER
from ..models.model_configuration import LLMModelConfiguration
from ..models.provider_keys import LLMProvider, LLMProviderKey
from .metrics import llma_track_latency


class LLMModelInfoSerializer(serializers.Serializer):
    id = serializers.CharField(
        help_text="Provider-specific model identifier (e.g. 'gpt-4o-mini', 'claude-3-5-sonnet-20241022')."
    )
    posthog_available = serializers.BooleanField(
        help_text="Whether this model is available on PostHog's trial credits without bringing a provider key."
    )


@extend_schema_serializer(many=False)
class LLMModelsListResponseSerializer(serializers.Serializer):
    models = LLMModelInfoSerializer(many=True, help_text="Models supported for the requested provider.")


class LLMModelsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """List available models for a provider."""

    scope_object = "evaluation"
    serializer_class = _FallbackSerializer
    permission_classes = [IsAuthenticated, AccessControlPermission]

    @extend_schema(
        operation_id="llm_analytics_models_retrieve",
        parameters=[
            OpenApiParameter(
                name="provider",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                enum=[choice[0] for choice in LLMProvider.choices],
                description="LLM provider to list models for. Must be one of the supported providers.",
            ),
            OpenApiParameter(
                name="key_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Optional provider key UUID. When supplied, models reachable with that specific key are "
                    "returned (useful for Azure OpenAI, where the deployment list depends on the configured "
                    "endpoint). Must belong to the same provider as the `provider` parameter."
                ),
            ),
        ],
        responses={200: LLMModelsListResponseSerializer},
    )
    @llma_track_latency("llma_models_list")
    @monitor(feature=None, endpoint="llma_models_list", method="GET")
    def list(self, request: Request, **_kwargs) -> Response:
        provider = request.query_params.get("provider")
        key_id = request.query_params.get("key_id")

        if not provider:
            return Response(
                {"detail": "provider query param is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if provider not in [choice[0] for choice in LLMProvider.choices]:
            return Response(
                {"detail": f"Invalid provider. Must be one of: {', '.join([c[0] for c in LLMProvider.choices])}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        provider_key = None
        if key_id:
            try:
                provider_key = LLMProviderKey.objects.get(id=key_id, team_id=self.team_id)
                if provider_key.provider != provider:
                    return Response(
                        {
                            "detail": f"Key provider '{provider_key.provider}' does not match requested provider '{provider}'"
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except LLMProviderKey.DoesNotExist:
                return Response(
                    {"detail": "Key not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        config = LLMModelConfiguration(
            provider=provider,
            provider_key=provider_key,
            team_id=self.team_id,
        )
        available = config.get_available_models()
        posthog_allowed = TRIAL_MODELS_BY_PROVIDER.get(provider, [])

        return Response(
            {"models": [{"id": model, "posthog_available": model in posthog_allowed} for model in available]}
        )
