"""
Workflow LLM completion endpoint.

POST /api/llm/workflow/completion

Called by the workflow engine (Node.js async function) to make LLM completion
requests using team-configured provider keys (BYOK). Authenticated via Bearer
token with the team's secret_api_token.
"""

import hashlib

from django.db.models import Q
from django.utils import timezone

import structlog
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.models import Team

from products.llm_analytics.backend.llm.client import Client
from products.llm_analytics.backend.llm.types import CompletionRequest
from products.llm_analytics.backend.models.provider_keys import LLMProvider, LLMProviderKey

logger = structlog.get_logger(__name__)


class _WorkflowLLMThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token (team secret_api_token)."""

    def get_cache_key(self, request, view):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        ident = hashlib.sha256(token.encode()).hexdigest() if token else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class WorkflowLLMBurstThrottle(_WorkflowLLMThrottle):
    scope = "workflow_llm_burst"
    rate = "60/minute"


class WorkflowLLMSustainedThrottle(_WorkflowLLMThrottle):
    scope = "workflow_llm_sustained"
    rate = "600/hour"


def _authenticate_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Extract Bearer token from Authorization header and resolve team."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, Response({"error": "Missing or invalid Authorization header"}, status=status.HTTP_401_UNAUTHORIZED)

    api_key = auth_header[7:].strip()
    if not api_key:
        return None, Response({"error": "Empty API key"}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        team = Team.objects.get(Q(secret_api_token=api_key) | Q(secret_api_token_backup=api_key))
    except (Team.DoesNotExist, Team.MultipleObjectsReturned):
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    return team, None


class WorkflowLLMCompletionSerializer(serializers.Serializer):
    provider_key_id = serializers.UUIDField()
    provider = serializers.ChoiceField(choices=LLMProvider.choices)
    model = serializers.CharField()
    messages = serializers.ListField(child=serializers.DictField())
    system = serializers.CharField(required=False, allow_blank=True)
    temperature = serializers.FloatField(required=False)
    max_tokens = serializers.IntegerField(required=False)


class WorkflowLLMCompletionView(APIView):
    """
    POST /api/llm/workflow/completion

    Non-streaming LLM completion for workflow actions.
    Authenticated via Bearer token (team secret_api_token).
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [WorkflowLLMBurstThrottle, WorkflowLLMSustainedThrottle]

    def post(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        serializer = WorkflowLLMCompletionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        try:
            provider_key = LLMProviderKey.objects.get(id=data["provider_key_id"], team=team)
        except LLMProviderKey.DoesNotExist:
            return Response({"error": "Provider key not found"}, status=status.HTTP_404_NOT_FOUND)

        api_key = provider_key.encrypted_config.get("api_key")
        if not api_key:
            return Response(
                {"error": "No API key configured for this provider key"}, status=status.HTTP_400_BAD_REQUEST
            )

        if provider_key.provider != data["provider"]:
            return Response(
                {
                    "error": f"Provider mismatch: key is for '{provider_key.provider}', request is for '{data['provider']}'"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        provider_key.last_used_at = timezone.now()
        provider_key.save(update_fields=["last_used_at"])

        try:
            client = Client(provider_key=provider_key, capture_analytics=False)
            completion_request = CompletionRequest(
                model=data["model"],
                messages=data["messages"],
                provider=data["provider"],
                system=data.get("system"),
                temperature=data.get("temperature"),
                max_tokens=data.get("max_tokens"),
            )
            response = client.complete(completion_request)
        except Exception as e:
            logger.exception("workflow_llm_completion_error", team_id=team.id, error=str(e))
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        result = {
            "content": response.content,
            "model": response.model,
        }
        if response.usage:
            result["usage"] = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

        return Response(result)
