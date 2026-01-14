"""OpenAI provider for unified LLM client."""

import uuid
import logging
from collections.abc import Generator
from typing import Any

from django.conf import settings

import openai
import posthoganalytics
from openai.types import CompletionUsage, ReasoningEffort
from openai.types.chat import ChatCompletionDeveloperMessageParam, ChatCompletionSystemMessageParam
from posthoganalytics.ai.openai import OpenAI
from pydantic import BaseModel

from products.llm_analytics.backend.llm.errors import AuthenticationError, QuotaExceededError, RateLimitError
from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    Usage,
)
from products.llm_analytics.backend.providers.formatters.openai_formatter import convert_to_openai_messages
from products.llm_analytics.backend.providers.formatters.tools_handler import LLMToolsHandler, ToolFormat

logger = logging.getLogger(__name__)


class OpenAIConfig:
    REASONING_EFFORT: ReasoningEffort = "medium"
    TEMPERATURE: float = 0

    SUPPORTED_MODELS: list[str] = [
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "o3-mini",
        "o3",
        "o3-pro",
        "o4-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
    ]

    SUPPORTED_MODELS_WITH_THINKING: list[str] = [
        "o3",
        "o3-pro",
        "o4-mini",
        "o3-mini",
        "gpt-5",
        "gpt-5-mini",
    ]


class OpenAIAdapter:
    """OpenAI provider implementing the unified Client interface."""

    name = "openai"

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
    ) -> CompletionResponse:
        """Non-streaming completion with optional structured output."""
        effective_api_key = api_key or self._get_default_api_key()

        posthog_client = posthoganalytics.default_client
        if analytics.capture and posthog_client:
            client = OpenAI(
                api_key=effective_api_key,
                posthog_client=posthog_client,
                base_url=settings.OPENAI_BASE_URL,
            )
        else:
            client = openai.OpenAI(api_key=effective_api_key, base_url=settings.OPENAI_BASE_URL)

        messages = self._build_messages(request)

        try:
            if request.response_format and issubclass(request.response_format, BaseModel):
                response = client.beta.chat.completions.parse(
                    model=request.model,
                    messages=messages,
                    response_format=request.response_format,
                    **(self._build_analytics_kwargs(analytics, client)),
                )
                parsed = response.choices[0].message.parsed
                content = parsed.model_dump_json() if parsed else ""
                usage = self._extract_usage(response.usage)
                return CompletionResponse(
                    content=content,
                    model=request.model,
                    usage=usage,
                    parsed=parsed,
                )
            else:
                response = client.chat.completions.create(
                    model=request.model,
                    messages=messages,
                    temperature=request.temperature if request.temperature is not None else OpenAIConfig.TEMPERATURE,
                    max_completion_tokens=request.max_tokens,
                    **(self._build_analytics_kwargs(analytics, client)),
                )
                content = response.choices[0].message.content or ""
                usage = self._extract_usage(response.usage)
                return CompletionResponse(
                    content=content,
                    model=request.model,
                    usage=usage,
                )
        except openai.AuthenticationError as e:
            raise AuthenticationError(str(e))
        except openai.RateLimitError as e:
            error_body = getattr(e, "body", {}) or {}
            error_code = error_body.get("error", {}).get("code", "")
            if error_code == "insufficient_quota":
                raise QuotaExceededError(str(e))
            raise RateLimitError(str(e))

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
            client: openai.OpenAI = OpenAI(
                api_key=effective_api_key,
                posthog_client=posthog_client,
                base_url=settings.OPENAI_BASE_URL,
            )
        else:
            client = openai.OpenAI(api_key=effective_api_key, base_url=settings.OPENAI_BASE_URL)

        supports_reasoning = model_id in OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING
        reasoning_on = supports_reasoning and (request.thinking or bool(request.reasoning_level))

        tools = self._convert_tools(request.tools) if request.tools else None

        try:
            effective_temperature = request.temperature if request.temperature is not None else OpenAIConfig.TEMPERATURE

            def build_common_kwargs() -> dict[str, Any]:
                common: dict[str, Any] = {
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if analytics.capture:
                    common["posthog_distinct_id"] = analytics.distinct_id
                    common["posthog_trace_id"] = analytics.trace_id or str(uuid.uuid4())
                    common["posthog_properties"] = analytics.properties or {}
                    common["posthog_groups"] = analytics.groups or {}
                if model_id not in OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING:
                    common["temperature"] = effective_temperature
                if request.max_tokens is not None:
                    common["max_completion_tokens"] = request.max_tokens
                if tools is not None:
                    common["tools"] = tools
                return common

            messages = request.messages
            system = request.system or ""

            if supports_reasoning:
                selected_effort: ReasoningEffort | None = None
                if request.reasoning_level in ("minimal", "low", "medium", "high"):
                    selected_effort = request.reasoning_level  # type: ignore[assignment]
                elif reasoning_on:
                    selected_effort = OpenAIConfig.REASONING_EFFORT
                stream = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        ChatCompletionDeveloperMessageParam({"role": "developer", "content": system}),
                        *convert_to_openai_messages(messages),
                    ],
                    reasoning_effort=selected_effort,
                    **build_common_kwargs(),
                )
            else:
                stream = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        ChatCompletionSystemMessageParam({"role": "system", "content": system}),
                        *convert_to_openai_messages(messages),
                    ],
                    **build_common_kwargs(),
                )

            for chunk in stream:
                if len(chunk.choices) > 0:
                    choice = chunk.choices[0]
                    if choice.delta.content:
                        yield StreamChunk(type="text", data={"text": choice.delta.content})
                    if choice.delta.tool_calls:
                        for tool_call in choice.delta.tool_calls:
                            yield StreamChunk(
                                type="tool_call",
                                data={
                                    "id": tool_call.id,
                                    "function": {
                                        "name": tool_call.function.name if tool_call.function.name else "",
                                        "arguments": tool_call.function.arguments
                                        if tool_call.function.arguments
                                        else "",
                                    },
                                },
                            )
                if chunk.usage:
                    yield from self._yield_usage_chunks(chunk.usage)

        except Exception as e:
            logger.exception(f"OpenAI API error: {e}")
            yield StreamChunk(type="error", data={"error": str(e)})

    @staticmethod
    def validate_key(api_key: str) -> tuple[str, str | None]:
        """Validate an OpenAI API key."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        if not api_key.startswith(("sk-", "sk-proj-")):
            return (LLMProviderKey.State.INVALID, "Invalid key format (should start with 'sk-' or 'sk-proj-')")
        try:
            client = openai.OpenAI(api_key=api_key)
            client.models.list()
            return (LLMProviderKey.State.OK, None)
        except openai.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except openai.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except openai.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to OpenAI")
        except Exception as e:
            logger.exception(f"OpenAI key validation error: {e}")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def list_models(api_key: str | None = None) -> list[str]:
        """List available OpenAI models."""
        if api_key:
            try:
                client = openai.OpenAI(api_key=api_key)
                all_models = [m.id for m in client.models.list()]
                return [
                    m
                    for m in all_models
                    if m in OpenAIConfig.SUPPORTED_MODELS or m.startswith(("gpt-", "o1", "o3", "o4"))
                ]
            except Exception as e:
                logger.exception(f"Error listing OpenAI models: {e}")
                return OpenAIConfig.SUPPORTED_MODELS
        return OpenAIConfig.SUPPORTED_MODELS

    @staticmethod
    def get_api_key() -> str:
        """Get the default API key from settings."""
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in environment or settings")
        return api_key

    def _get_default_api_key(self) -> str:
        return self.get_api_key()

    def _build_messages(self, request: CompletionRequest) -> list[dict]:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend(request.messages)
        return messages

    def _build_analytics_kwargs(self, analytics: AnalyticsContext, client) -> dict:
        if analytics.capture and isinstance(client, OpenAI):
            return {
                "posthog_distinct_id": analytics.distinct_id,
                "posthog_trace_id": analytics.trace_id or str(uuid.uuid4()),
                "posthog_properties": analytics.properties or {},
                "posthog_groups": analytics.groups or {},
            }
        return {}

    def _extract_usage(self, usage) -> Usage | None:
        if not usage:
            return None
        cache_read = 0
        if usage.prompt_tokens_details and usage.prompt_tokens_details.cached_tokens:
            cache_read = usage.prompt_tokens_details.cached_tokens
        return Usage(
            input_tokens=usage.prompt_tokens or 0,
            output_tokens=usage.completion_tokens or 0,
            total_tokens=usage.total_tokens or 0,
            cache_read_tokens=cache_read,
        )

    def _yield_usage_chunks(self, usage: CompletionUsage) -> Generator[StreamChunk, None, None]:
        input_tokens = usage.prompt_tokens or 0
        output_tokens = usage.completion_tokens or 0
        cache_read_tokens = (
            usage.prompt_tokens_details.cached_tokens
            if usage.prompt_tokens_details and usage.prompt_tokens_details.cached_tokens is not None
            else 0
        )
        non_cached_input_tokens = max(0, input_tokens - cache_read_tokens)
        yield StreamChunk(
            type="usage",
            data={
                "input_tokens": non_cached_input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": 0,
            },
        )

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        handler = LLMToolsHandler(tools)
        return handler.convert_to(ToolFormat.OPENAI)


# Backward compatibility alias
OpenAIProvider = OpenAIAdapter
