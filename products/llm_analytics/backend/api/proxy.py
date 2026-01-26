"""
ViewSet for LLM Analytics Proxy

Endpoints:
- GET /api/llm_proxy/models
- POST /api/llm_proxy/completion
"""

import json
import uuid
import logging
from collections.abc import Generator
from typing import Any, cast

from django.http import StreamingHttpResponse
from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import SessionAuthentication
from posthog.event_usage import groups, report_user_action
from posthog.models import User
from posthog.rate_limit import LLMProxyBurstRateThrottle, LLMProxyDailyRateThrottle, LLMProxySustainedRateThrottle
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from posthog.settings import SERVER_GATEWAY_INTERFACE

from products.llm_analytics.backend.llm import (
    SUPPORTED_MODELS_WITH_THINKING,
    Client,
    CompletionRequest,
    get_default_models,
)
from products.llm_analytics.backend.llm.errors import UnsupportedProviderError
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

from ee.hogai.utils.asgi import SyncIterableToAsync

logger = logging.getLogger(__name__)


class LLMProxyCompletionSerializer(serializers.Serializer):
    system = serializers.CharField(allow_blank=True)
    messages = serializers.ListField(child=serializers.DictField())
    model = serializers.CharField()
    provider = serializers.ChoiceField(choices=["openai", "anthropic", "gemini"])
    thinking = serializers.BooleanField(default=False, required=False)
    temperature = serializers.FloatField(required=False)
    max_tokens = serializers.IntegerField(required=False)
    tools = serializers.JSONField(required=False)
    reasoning_level = serializers.ChoiceField(
        choices=["minimal", "low", "medium", "high"], required=False, allow_null=True
    )
    provider_key_id = serializers.UUIDField(required=False, allow_null=True)


class LLMProxyViewSet(viewsets.ViewSet):
    """
    ViewSet for LLM Analytics Proxy
    Proxies LLM calls from the llm analytics playground
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]

    def get_throttles(self):
        # Don't throttle the models list endpoint - it returns a static list
        # and should always be accessible even if the user hit rate limits on completions
        if self.action == "models":
            return []

        return [LLMProxyBurstRateThrottle(), LLMProxySustainedRateThrottle(), LLMProxyDailyRateThrottle()]

    def _get_provider_key(self, provider_key_id: str | None, user) -> LLMProviderKey | None:
        """
        Fetch provider key by ID.
        Returns LLMProviderKey or None if no key ID provided.
        Raises ValueError if key not found or user doesn't have access.
        """
        if not provider_key_id:
            return None

        team = getattr(user, "current_team", None)
        if not team:
            raise ValueError("No team associated with user")

        try:
            key = LLMProviderKey.objects.get(id=provider_key_id, team=team)
        except LLMProviderKey.DoesNotExist:
            raise ValueError("Provider key not found")

        api_key = key.encrypted_config.get("api_key")
        if not api_key:
            raise ValueError("No API key configured for this provider key")

        key.last_used_at = timezone.now()
        key.save(update_fields=["last_used_at"])

        return key

    def validate_messages(self, messages: list[dict[str, Any]]) -> bool:
        if not messages:
            return False
        for msg in messages:
            if "role" not in msg or "content" not in msg:
                return False
        return True

    def _create_stream_generator(
        self, client: Client, request_obj: CompletionRequest, http_request
    ) -> Generator[bytes, None, None]:
        """Creates a generator that handles client disconnects and encodes responses"""
        try:
            for chunk in client.stream(request_obj):
                if not http_request.META.get("SERVER_NAME"):  # Client disconnected
                    return
                yield chunk.to_sse().encode()
        except Exception as e:
            logger.exception(f"Error in LLM proxy stream: {e}")
            yield f"data: {json.dumps({'error': 'An internal error occurred', 'status_code': 500})}\n\n".encode()

    def _create_streaming_response(self, stream: Generator[bytes, None, None]) -> StreamingHttpResponse:
        """Creates a properly configured SSE streaming response"""
        if SERVER_GATEWAY_INTERFACE == "ASGI":
            astream = SyncIterableToAsync(stream)
            response = StreamingHttpResponse(streaming_content=astream, content_type=ServerSentEventRenderer.media_type)
        else:
            response = StreamingHttpResponse(streaming_content=stream, content_type=ServerSentEventRenderer.media_type)
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    def _handle_completion_request(self, request: Request) -> StreamingHttpResponse | Response:
        """Handler for completion requests using unified Client"""
        try:
            if not request.user or not request.user.is_authenticated:
                return Response({"error": "You are not authorized to use this feature"}, status=401)

            organization = request.user.organization
            if not organization or not organization.customer_id:
                return Response(
                    {"error": "The playground requires a valid payment method on file to prevent abuse."},
                    status=402,
                )

            serializer = LLMProxyCompletionSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({"error": serializer.errors}, status=400)

            data = serializer.validated_data
            model = data.get("model")
            thinking = data.get("thinking", False)

            # Validate thinking support
            if thinking and model not in SUPPORTED_MODELS_WITH_THINKING:
                return Response({"error": "Thinking is not supported for this model"}, status=400)

            # Validate messages
            messages = data.get("messages")
            if not self.validate_messages(messages):
                return Response({"error": "Invalid messages"}, status=400)

            # Fetch BYOK key if provider_key_id is specified
            provider_key_id = data.get("provider_key_id")
            try:
                provider_key = self._get_provider_key(provider_key_id, request.user)
            except ValueError:
                return Response({"error": "Invalid provider key configuration"}, status=400)

            # Provider is always explicit from request
            provider = data.get("provider")

            # Generate tracking parameters for PostHog analytics
            trace_id = str(uuid.uuid4())
            distinct_id = getattr(request.user, "email", "") if request.user and request.user.is_authenticated else ""
            properties = {"ai_product": "playground"}
            group_properties = groups(team=getattr(request.user, "current_team", None))

            # Create Client with analytics context
            client = Client(
                provider_key=provider_key,
                distinct_id=distinct_id,
                trace_id=trace_id,
                properties=properties,
                groups=group_properties,
            )

            # Build completion request
            completion_request = CompletionRequest(
                model=model,
                messages=messages,
                provider=provider,
                system=data.get("system"),
                temperature=data.get("temperature"),
                max_tokens=data.get("max_tokens"),
                tools=data.get("tools"),
                thinking=thinking,
                reasoning_level=data.get("reasoning_level"),
            )

            # Create stream
            stream = self._create_stream_generator(client, completion_request, request)

            # Track playground completion started
            tracking_properties = self._extract_request_properties(data, model=model)
            tracking_properties["trace_id"] = trace_id

            report_user_action(
                cast(User, request.user),
                "llma playground completion started",
                tracking_properties,
                getattr(request.user, "current_team", None),
            )

            return self._create_streaming_response(stream)

        except UnsupportedProviderError:
            return Response({"error": "Unsupported provider"}, status=400)

        except Exception as e:
            logger.exception(f"Error in LLM proxy: {e}")

            # Track playground completion failed
            if request.user and request.user.is_authenticated:
                error_properties: dict[str, Any] = {
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                }

                # Try to extract request parameters to understand failure context
                try:
                    serializer = LLMProxyCompletionSerializer(data=request.data)
                    if serializer.is_valid():
                        request_properties = self._extract_request_properties(serializer.validated_data)
                        error_properties.update(request_properties)
                    else:
                        error_properties["validation_errors"] = serializer.errors
                except Exception:
                    pass

                report_user_action(
                    cast(User, request.user),
                    "llma playground completion failed",
                    error_properties,
                    getattr(request.user, "current_team", None),
                )

            return Response({"error": "An internal error occurred"}, status=500)

    def _extract_request_properties(self, validated_data: dict, model: str | None = None) -> dict:
        """Extract common properties from request for event tracking"""
        model_name = model or validated_data.get("model")
        properties = {
            "model": model_name,
            "thinking_enabled": validated_data.get("thinking", False),
            "has_tools": bool(validated_data.get("tools")),
            "has_temperature": validated_data.get("temperature") is not None,
            "has_max_tokens": validated_data.get("max_tokens") is not None,
            "has_reasoning_level": validated_data.get("reasoning_level") is not None,
            "has_system_prompt": bool(validated_data.get("system")),
        }

        # Add tool count if tools are present
        if validated_data.get("tools"):
            properties["tool_count"] = len(validated_data.get("tools", []))

        # Add message count if messages are present
        messages = validated_data.get("messages")
        if messages:
            properties["message_count"] = len(messages)

        # Get provider from validated data (now mandatory)
        if validated_data.get("provider"):
            properties["provider"] = validated_data["provider"]

        return properties

    @action(detail=False, methods=["GET"])
    def models(self, request):
        """Return a list of available models across providers.

        If provider_key_id is specified, returns models available for that key.
        Otherwise, returns the default static list of models.
        """
        provider_key_id = request.query_params.get("provider_key_id")

        if provider_key_id:
            try:
                provider_key = self._get_provider_key(provider_key_id, request.user)
            except ValueError:
                return Response({"error": "Invalid provider key configuration"}, status=400)

            if provider_key:
                api_key = provider_key.encrypted_config.get("api_key")
                models = Client.list_models(provider_key.provider, api_key)
                provider_display = provider_key.provider.title()
                return Response([{"id": m, "name": m, "provider": provider_display, "description": ""} for m in models])

        # Default: return static list of all supported models
        return Response(get_default_models())

    @action(detail=False, methods=["POST"])
    def completion(self, request, *args, **kwargs):
        return self._handle_completion_request(request)
