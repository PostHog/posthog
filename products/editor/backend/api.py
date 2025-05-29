"""
ViewSet for Editor Proxy
"""

import json
import posthoganalytics
from rest_framework import viewsets
from posthog.auth import PersonalAPIKeyAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers
from rest_framework.renderers import BaseRenderer
from rest_framework.decorators import action
from rest_framework.request import Request
from django.http import StreamingHttpResponse
from rest_framework.response import Response
from posthog.rate_limit import EditorProxyBurstRateThrottle, EditorProxySustainedRateThrottle
from .providers.anthropic import AnthropicProvider, AnthropicConfig
from .providers.codestral import CodestralProvider
from .providers.inkeep import InkeepProvider
from posthog.settings import SERVER_GATEWAY_INTERFACE
from ee.hogai.utils.asgi import SyncIterableToAsync
from collections.abc import Generator, Callable
from typing import Any
import logging

logger = logging.getLogger(__name__)


class ServerSentEventRenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "txt"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, dict | list):
            return None
        return data


class JSONRenderer(BaseRenderer):
    media_type = "application/json"
    format = "json"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, dict | list):
            return json.dumps(data).encode()
        return None


SUPPORTED_MODELS_WITH_THINKING = AnthropicConfig.SUPPORTED_MODELS_WITH_THINKING


class LLMProxyCompletionSerializer(serializers.Serializer):
    system = serializers.CharField(allow_blank=True)
    messages = serializers.ListField(child=serializers.DictField())
    model = serializers.CharField()
    thinking = serializers.BooleanField(default=False, required=False)


class LLMProxyFIMSerializer(serializers.Serializer):
    prompt = serializers.CharField()
    suffix = serializers.CharField()
    model = serializers.CharField()
    stop = serializers.ListField(child=serializers.CharField())


class LLMProxyViewSet(viewsets.ViewSet):
    """
    ViewSet for Editor Proxy
    Proxies LLM calls from the editor
    """

    authentication_classes = [PersonalAPIKeyAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer, ServerSentEventRenderer]

    def get_throttles(self):
        return [EditorProxyBurstRateThrottle(), EditorProxySustainedRateThrottle()]

    def validate_feature_flag(self, request):
        result = PersonalAPIKeyAuthentication().authenticate(request)
        if result is None:
            return False
        user, _ = result
        return posthoganalytics.feature_enabled("llm-editor-proxy", user.email, person_properties={"email": user.email})

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
        provider_factory: Callable[[dict], Any],
        mode: str = "completion",
    ) -> StreamingHttpResponse | Response:
        """Generic handler for LLM proxy requests"""
        try:
            valid_feature_flag = self.validate_feature_flag(request)
            if not valid_feature_flag:
                return Response({"error": "You are not authorized to use this feature"}, status=400)

            serializer = serializer_class(data=request.data)
            if not serializer.is_valid():
                return Response({"error": serializer.errors}, status=400)

            provider = provider_factory(serializer.validated_data)
            if isinstance(provider, Response):  # Error response
                return provider

            if mode == "completion" and hasattr(provider, "stream_response"):
                stream = self._create_stream_generator(
                    provider.stream_response(
                        **{
                            "system": serializer.validated_data.get("system"),
                            "messages": serializer.validated_data.get("messages"),
                            "thinking": serializer.validated_data.get("thinking", False),
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

    def _get_completion_provider(self, data: dict) -> Any:
        """Factory method for completion providers"""
        model_id = data.get("model")
        thinking = data.get("thinking", False)

        if thinking and model_id not in SUPPORTED_MODELS_WITH_THINKING:
            return Response({"error": "Thinking is not supported for this model"}, status=400)

        match model_id:
            case (
                "claude-3-7-sonnet-20250219"
                | "claude-3-5-sonnet-20241022"
                | "claude-3-5-haiku-20241022"
                | "claude-3-opus-20240229"
                | "claude-3-haiku-20240307"
            ):
                return AnthropicProvider(model_id)
            case "inkeep-qa-expert":
                return InkeepProvider(model_id)
            case _:
                return Response({"error": "Unsupported model"}, status=400)

    def _get_fim_provider(self, data: dict) -> Any:
        """Factory method for FIM providers"""
        model = data.get("model")
        match model:
            case "codestral-latest":
                return CodestralProvider(model)
            case _:
                return Response({"error": "Unsupported model"}, status=400)

    @action(detail=False, methods=["POST"])
    def completion(self, request, *args, **kwargs):
        return self._handle_request(
            request, LLMProxyCompletionSerializer, self._get_completion_provider, mode="completion"
        )

    @action(detail=False, methods=["POST"], url_path="fim/completion")
    def fimCompletion(self, request, *args, **kwargs):
        return self._handle_request(request, LLMProxyFIMSerializer, self._get_fim_provider, mode="fim")
