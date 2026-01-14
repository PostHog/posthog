"""Gemini provider for unified LLM client."""

import json
import uuid
import logging
from collections.abc import Generator
from typing import Any

from django.conf import settings

import posthoganalytics
from google import genai
from google.genai.errors import APIError
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai as posthog_genai

from products.llm_analytics.backend.llm.errors import AuthenticationError
from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    Usage,
)
from products.llm_analytics.backend.providers.formatters.gemini_formatter import convert_anthropic_messages_to_gemini

logger = logging.getLogger(__name__)


class GeminiConfig:
    TEMPERATURE: float = 0

    SUPPORTED_MODELS: list[str] = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash-preview-09-2025",
        "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]


class GeminiAdapter:
    """Gemini provider implementing the unified Client interface."""

    name = "gemini"

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
    ) -> CompletionResponse:
        """Non-streaming completion."""
        effective_api_key = api_key or self._get_default_api_key()

        posthog_client = posthoganalytics.default_client
        if analytics.capture and posthog_client:
            client = posthog_genai.Client(api_key=effective_api_key, posthog_client=posthog_client)
        else:
            client = genai.Client(api_key=effective_api_key)

        config_kwargs = self._prepare_config_kwargs(
            system=request.system or "",
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=request.tools,
        )

        try:
            contents = convert_anthropic_messages_to_gemini(request.messages)

            response = client.models.generate_content(
                model=request.model,
                contents=contents,
                config=GenerateContentConfig(**config_kwargs),
                **(self._build_analytics_kwargs(analytics, client)),
            )
            content = response.text or ""
            usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = Usage(
                    input_tokens=response.usage_metadata.prompt_token_count or 0,
                    output_tokens=response.usage_metadata.candidates_token_count or 0,
                    total_tokens=response.usage_metadata.total_token_count or 0,
                )
            return CompletionResponse(
                content=content,
                model=request.model,
                usage=usage,
            )
        except Exception as e:
            if "authentication" in str(e).lower() or "api key" in str(e).lower():
                raise AuthenticationError(str(e))
            raise

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
    ) -> Generator[StreamChunk, None, None]:
        """Streaming completion."""
        effective_api_key = api_key or self._get_default_api_key()
        model_id = request.model

        posthog_client = posthoganalytics.default_client
        if analytics.capture and posthog_client:
            client: genai.Client = posthog_genai.Client(api_key=effective_api_key, posthog_client=posthog_client)
        else:
            client = genai.Client(api_key=effective_api_key)

        tools = self._convert_tools(request.tools) if request.tools else None

        config_kwargs = self._prepare_config_kwargs(
            system=request.system or "",
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=tools,
        )

        analytics_kwargs: dict[str, Any] = {}
        if analytics.capture:
            analytics_kwargs = {
                "posthog_distinct_id": analytics.distinct_id,
                "posthog_trace_id": analytics.trace_id or str(uuid.uuid4()),
                "posthog_properties": analytics.properties or {},
                "posthog_groups": analytics.groups or {},
            }

        try:
            response = client.models.generate_content_stream(
                model=model_id,
                contents=convert_anthropic_messages_to_gemini(request.messages),
                config=GenerateContentConfig(**config_kwargs),
                **analytics_kwargs,
            )

            for chunk in response:
                yield from self._extract_chunks_from_response(chunk)

                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    yield StreamChunk(
                        type="usage",
                        data={
                            "input_tokens": chunk.usage_metadata.prompt_token_count or 0,
                            "output_tokens": chunk.usage_metadata.candidates_token_count or 0,
                        },
                    )

        except APIError as e:
            logger.exception(f"Gemini API error when streaming response: {e}")
            yield StreamChunk(type="error", data={"error": "Gemini API error"})
        except Exception as e:
            logger.exception(f"Unexpected error when streaming response: {e}")
            yield StreamChunk(type="error", data={"error": "Unexpected error"})

    @staticmethod
    def validate_key(api_key: str) -> tuple[str, str | None]:
        """Validate a Gemini API key."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        try:
            client = genai.Client(api_key=api_key)
            list(client.models.list())
            return (LLMProviderKey.State.OK, None)
        except Exception as e:
            logger.exception(f"Gemini key validation error: {e}")
            return (LLMProviderKey.State.INVALID, "Invalid API key")

    @staticmethod
    def list_models(api_key: str | None = None) -> list[str]:
        """List available Gemini models."""
        if api_key:
            try:
                client = genai.Client(api_key=api_key)
                all_models = [m.name for m in client.models.list()]
                return [m.replace("models/", "") for m in all_models if "gemini" in m.lower()]
            except Exception as e:
                logger.exception(f"Error listing Gemini models: {e}")
                return GeminiConfig.SUPPORTED_MODELS
        return GeminiConfig.SUPPORTED_MODELS

    @staticmethod
    def get_api_key() -> str:
        """Get the default API key from settings."""
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment or settings")
        return api_key

    def _get_default_api_key(self) -> str:
        return self.get_api_key()

    @staticmethod
    def _prepare_config_kwargs(
        system: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Prepare Gemini config kwargs."""
        effective_temperature = temperature if temperature is not None else GeminiConfig.TEMPERATURE
        config_kwargs: dict[str, Any] = {
            "temperature": effective_temperature,
        }
        if system:
            config_kwargs["system_instruction"] = system
        if max_tokens is not None:
            config_kwargs["max_output_tokens"] = max_tokens
        if tools is not None:
            config_kwargs["tools"] = tools
        return config_kwargs

    def _build_analytics_kwargs(self, analytics: AnalyticsContext, client) -> dict:
        """Build PostHog analytics kwargs if using instrumented client."""
        if analytics.capture and isinstance(client, posthog_genai.Client):
            return {
                "posthog_distinct_id": analytics.distinct_id,
                "posthog_trace_id": analytics.trace_id or str(uuid.uuid4()),
                "posthog_properties": analytics.properties or {},
                "posthog_groups": analytics.groups or {},
            }
        return {}

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert tools to Gemini format if needed."""
        from products.llm_analytics.backend.providers.formatters.tools_handler import LLMToolsHandler, ToolFormat

        handler = LLMToolsHandler(tools)
        return handler.convert_to(ToolFormat.GEMINI)

    def _extract_chunks_from_response(self, chunk) -> Generator[StreamChunk, None, None]:
        """Extract StreamChunks from a Gemini response chunk."""
        if hasattr(chunk, "text") and chunk.text:
            yield StreamChunk(type="text", data={"text": chunk.text})
            return

        if hasattr(chunk, "candidates") and chunk.candidates:
            for candidate in chunk.candidates:
                if hasattr(candidate, "content") and candidate.content:
                    if hasattr(candidate.content, "parts") and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, "function_call") and part.function_call:
                                yield StreamChunk(
                                    type="tool_call",
                                    data={
                                        "id": f"gemini_tool_{hash(str(part.function_call))}",
                                        "function": {
                                            "name": part.function_call.name,
                                            "arguments": (
                                                json.dumps(dict(part.function_call.args))
                                                if part.function_call.args
                                                else "{}"
                                            ),
                                        },
                                    },
                                )
                            elif hasattr(part, "text") and part.text:
                                yield StreamChunk(type="text", data={"text": part.text})


# Backward compatibility alias
GeminiProvider = GeminiAdapter
