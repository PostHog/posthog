"""
ViewSet for LLM Observability Proxy

Endpoints:
- GET /api/llm_proxy/models
- POST /api/llm_proxy/completion
- POST /api/llm_proxy/fim/completion
"""

import json
import posthoganalytics
import uuid
from rest_framework import viewsets
from posthog.auth import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from django.http import StreamingHttpResponse
from rest_framework.response import Response
from posthog.rate_limit import LLMProxyBurstRateThrottle, LLMProxySustainedRateThrottle
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from products.llm_observability.providers.anthropic import AnthropicProvider, AnthropicConfig
from products.llm_observability.providers.openai import OpenAIProvider, OpenAIConfig
from products.llm_observability.providers.codestral import CodestralProvider, CodestralConfig
from products.llm_observability.providers.inkeep import InkeepProvider, InkeepConfig
from products.llm_observability.providers.gemini import GeminiProvider, GeminiConfig
from posthog.settings import SERVER_GATEWAY_INTERFACE
from ee.hogai.utils.asgi import SyncIterableToAsync
from collections.abc import Generator, Callable
from typing import Any, TypedDict, TypeGuard
from anthropic.types import MessageParam
import logging

logger = logging.getLogger(__name__)


SUPPORTED_MODELS_WITH_THINKING = (
    AnthropicConfig.SUPPORTED_MODELS_WITH_THINKING + OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING
)


class LLMProxyCompletionSerializer(serializers.Serializer):
    system = serializers.CharField(allow_blank=True)
    messages = serializers.ListField(child=serializers.DictField())
    model = serializers.CharField()
    thinking = serializers.BooleanField(default=False, required=False)
    temperature = serializers.FloatField(required=False)
    max_tokens = serializers.IntegerField(required=False)


class LLMProxyFIMSerializer(serializers.Serializer):
    prompt = serializers.CharField()
    suffix = serializers.CharField()
    model = serializers.CharField()
    stop = serializers.ListField(child=serializers.CharField())


class ProviderData(TypedDict):
    model: str
    system: str
    messages: list[dict[str, Any]]
    thinking: bool


class LLMProxyViewSet(viewsets.ViewSet):
    """
    ViewSet for LLM Observability Proxy
    Proxies LLM calls from the llm observability playground
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]

    def get_throttles(self):
        return [LLMProxyBurstRateThrottle(), LLMProxySustainedRateThrottle()]

    def validate_feature_flag(self, request):
        if not request.user or not request.user.is_authenticated:
            return False

        llm_observability_enabled = posthoganalytics.feature_enabled(
            "llm-observability-playground", request.user.email, person_properties={"email": request.user.email}
        )
        return llm_observability_enabled

    def validate_messages(self, messages: list[dict[str, Any]]) -> TypeGuard[list[MessageParam]]:
        if not messages:
            return False
        for msg in messages:
            if "role" not in msg or "content" not in msg:
                return False
        return True

    def _create_stream_generator(
        self, provider_stream: Generator[str, None, None], request
    ) -> Generator[bytes, None, None]:
        """Creates a generator that handles client disconnects and encodes responses"""
        try:
            for chunk in provider_stream:
                if not request.META.get("SERVER_NAME"):  # Client disconnected
                    return
                yield chunk.encode()
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

    def _handle_request(
        self,
        request: Request,
        serializer_class: type[LLMProxyCompletionSerializer] | type[LLMProxyFIMSerializer],
        provider_factory: Callable[[ProviderData], Any],
        mode: str = "completion",
    ) -> StreamingHttpResponse | Response:
        """Generic handler for LLM proxy requests"""
        try:
            valid_feature_flag = self.validate_feature_flag(request)
            if not valid_feature_flag:
                return Response({"error": "You are not authorized to use this feature"}, status=401)

            serializer = serializer_class(data=request.data)
            if not serializer.is_valid():
                return Response({"error": serializer.errors}, status=400)

            provider = provider_factory(serializer.validated_data)
            if isinstance(provider, Response):  # Error response
                return provider

            # Generate tracking parameters for PostHog observability
            trace_id = str(uuid.uuid4())
            distinct_id = getattr(request.user, "email", "") if request.user and request.user.is_authenticated else ""
            properties = {"ai_product": "playground"}
            groups = {}  # placeholder for groups, maybe we should add team_id here or something????
            if request.user and request.user.is_authenticated:
                team_id = getattr(request.user, "team_id", None)
                if team_id:
                    groups["team"] = str(team_id)

            if mode == "completion" and hasattr(provider, "stream_response"):
                messages = serializer.validated_data.get("messages")
                if not self.validate_messages(messages):
                    return Response({"error": "Invalid messages"}, status=400)
                stream = self._create_stream_generator(
                    provider.stream_response(
                        **{
                            "system": serializer.validated_data.get("system"),
                            "messages": messages,
                            "thinking": serializer.validated_data.get("thinking", False),
                            "temperature": serializer.validated_data.get("temperature"),
                            "max_tokens": serializer.validated_data.get("max_tokens"),
                            "distinct_id": distinct_id,
                            "trace_id": trace_id,
                            "properties": properties,
                            "groups": groups,
                        }
                    ),
                    request,
                )
            elif mode == "fim" and hasattr(provider, "stream_fim_response"):
                stream = self._create_stream_generator(
                    provider.stream_fim_response(
                        **{
                            "prompt": serializer.validated_data.get("prompt"),
                            "suffix": serializer.validated_data.get("suffix"),
                            "stop": serializer.validated_data.get("stop"),
                            "temperature": serializer.validated_data.get("temperature"),
                            "max_tokens": serializer.validated_data.get("max_tokens"),
                            "distinct_id": distinct_id,
                            "trace_id": trace_id,
                            "properties": properties,
                            "groups": groups,
                        }
                    ),
                    request,
                )
            else:
                raise ValueError(f"Invalid mode: {mode} for provider: {provider}")

            return self._create_streaming_response(stream)

        except Exception as e:
            logger.exception(f"Error in LLM proxy: {e}")
            return Response({"error": "An internal error occurred"}, status=500)

    def _get_completion_provider(self, data: ProviderData) -> Any:
        """Factory method for completion providers"""
        model_id = data.get("model")
        thinking = data.get("thinking", False)

        if thinking and model_id not in SUPPORTED_MODELS_WITH_THINKING:
            return Response({"error": "Thinking is not supported for this model"}, status=400)

        match model_id:
            case model_id if model_id in AnthropicConfig.SUPPORTED_MODELS:
                return AnthropicProvider(model_id)
            case model_id if model_id in InkeepConfig.SUPPORTED_MODELS:
                return InkeepProvider(model_id)
            case model_id if model_id in OpenAIConfig.SUPPORTED_MODELS:
                return OpenAIProvider(model_id)
            case model_id if model_id in GeminiConfig.SUPPORTED_MODELS:
                return GeminiProvider(model_id)
            case _:
                return Response({"error": "Unsupported model"}, status=400)

    def _get_fim_provider(self, data: ProviderData) -> Any:
        """Factory method for FIM providers"""
        model_id = data.get("model")
        match model_id:
            case model_id if model_id in CodestralConfig.SUPPORTED_MODELS:
                return CodestralProvider(model_id)
            case _:
                return Response({"error": "Unsupported model"}, status=400)

    @action(detail=False, methods=["GET"])
    def models(self, request):
        """Return a list of available models across providers"""
        model_list: list[dict[str, str]] = []
        model_list += [
            {"id": m, "name": m, "provider": "OpenAI", "description": ""} for m in OpenAIConfig.SUPPORTED_MODELS
        ]
        model_list += [
            {"id": m, "name": m, "provider": "Anthropic", "description": ""} for m in AnthropicConfig.SUPPORTED_MODELS
        ]
        model_list += [
            {"id": m, "name": m, "provider": "Gemini", "description": ""} for m in GeminiConfig.SUPPORTED_MODELS
        ]
        return Response(model_list)

    @action(detail=False, methods=["POST"])
    def completion(self, request, *args, **kwargs):
        return self._handle_request(
            request, LLMProxyCompletionSerializer, self._get_completion_provider, mode="completion"
        )

    @action(detail=False, methods=["POST"], url_path="fim/completion")
    def fimCompletion(self, request, *args, **kwargs):
        return self._handle_request(request, LLMProxyFIMSerializer, self._get_fim_provider, mode="fim")
