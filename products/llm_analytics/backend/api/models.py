from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..models.model_configuration import POSTHOG_ALLOWED_MODELS, LLMModelConfiguration
from ..models.provider_keys import LLMProvider, LLMProviderKey


class LLMModelsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """List available models for a provider."""

    scope_object = "llm_provider_key"
    permission_classes = [IsAuthenticated]

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

        # Use LLMModelConfiguration to get available models
        config = LLMModelConfiguration(
            provider=provider,
            provider_key=provider_key,
            team_id=self.team_id,
        )
        available = config.get_available_models()
        posthog_allowed = POSTHOG_ALLOWED_MODELS.get(provider, [])

        return Response(
            {"models": [{"id": model, "posthog_available": model in posthog_allowed} for model in available]}
        )
