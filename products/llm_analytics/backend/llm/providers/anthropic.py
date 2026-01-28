"""Anthropic provider for unified LLM client."""

import json
import uuid
import logging
from collections.abc import Generator
from typing import Any

from django.conf import settings

import anthropic
import posthoganalytics
from anthropic.types import MessageParam, TextBlockParam, ThinkingConfigEnabledParam
from posthoganalytics.ai.anthropic import Anthropic
from pydantic import BaseModel

from products.llm_analytics.backend.llm.errors import AuthenticationError
from products.llm_analytics.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    Usage,
)

logger = logging.getLogger(__name__)


class AnthropicConfig:
    MAX_TOKENS: int = 8192
    MAX_THINKING_TOKENS: int = 4096
    TEMPERATURE: float = 0
    # Timeout in seconds for API calls. Set high to accommodate slow reasoning models.
    # Note: Infrastructure-level timeouts (load balancers, proxies) may still limit actual request duration.
    TIMEOUT: float = 300.0

    SUPPORTED_MODELS: list[str] = [
        "claude-sonnet-4-5",
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-4-0",
        "claude-opus-4-0",
        "claude-opus-4-20250514",
        "claude-opus-4-1-20250805",
        "claude-sonnet-4-20250514",
        "claude-3-7-sonnet-latest",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-haiku-4-5-20251001",
    ]

    SUPPORTED_MODELS_WITH_CACHE_CONTROL: list[str] = [
        "claude-sonnet-4-5",
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-20250514",
        "claude-opus-4-1-20250805",
        "claude-sonnet-4-20250514",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307",
    ]

    SUPPORTED_MODELS_WITH_THINKING: list[str] = [
        "claude-sonnet-4-5",
        "claude-sonnet-4-5-20250929",
        "claude-3-7-sonnet-20250219",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-opus-4-1-20250805",
    ]


class AnthropicAdapter:
    """Anthropic provider implementing the unified Client interface."""

    name = "anthropic"

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
    ) -> CompletionResponse:
        """Non-streaming completion with optional structured output."""
        effective_api_key = api_key or self._get_default_api_key()

        posthog_client = posthoganalytics.default_client
        client: Any
        if analytics.capture and posthog_client:
            client = Anthropic(
                api_key=effective_api_key, posthog_client=posthog_client, timeout=AnthropicConfig.TIMEOUT
            )
        else:
            client = anthropic.Anthropic(api_key=effective_api_key, timeout=AnthropicConfig.TIMEOUT)

        messages: Any = request.messages

        # Handle structured output by appending JSON schema instructions
        system_prompt = request.system or ""
        if request.response_format and issubclass(request.response_format, BaseModel):
            json_schema = request.response_format.model_json_schema()
            system_prompt = f"""{system_prompt}

You must respond with valid JSON that matches this schema:
{json.dumps(json_schema, indent=2)}

Return ONLY the JSON object, no other text or markdown formatting."""

        try:
            response = client.messages.create(
                model=request.model,
                system=system_prompt,
                messages=messages,
                max_tokens=request.max_tokens or AnthropicConfig.MAX_TOKENS,
                temperature=request.temperature if request.temperature is not None else AnthropicConfig.TEMPERATURE,
                **(self._build_analytics_kwargs(analytics, client)),
            )
            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text
            usage = Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            )

            # Parse structured output if response_format was specified
            parsed: BaseModel | None = None
            if request.response_format and issubclass(request.response_format, BaseModel):
                try:
                    # Clean up the content - remove markdown code blocks if present
                    clean_content = content.strip()
                    if clean_content.startswith("```"):
                        lines = clean_content.split("\n")
                        # Remove first and last lines (code block markers)
                        clean_content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                    parsed = request.response_format.model_validate_json(clean_content)
                except Exception as e:
                    logger.warning(f"Failed to parse structured output from Anthropic: {e}")
                    raise ValueError(f"Failed to parse structured output: {e}") from e

            return CompletionResponse(
                content=content,
                model=request.model,
                usage=usage,
                parsed=parsed,
            )
        except Exception as e:
            if "authentication" in str(e).lower() or "invalid api key" in str(e).lower():
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
        client: Any
        if analytics.capture and posthog_client:
            client = Anthropic(
                api_key=effective_api_key, posthog_client=posthog_client, timeout=AnthropicConfig.TIMEOUT
            )
        else:
            client = anthropic.Anthropic(api_key=effective_api_key, timeout=AnthropicConfig.TIMEOUT)

        reasoning_on = model_id in AnthropicConfig.SUPPORTED_MODELS_WITH_THINKING and request.thinking

        effective_temperature = request.temperature if request.temperature is not None else AnthropicConfig.TEMPERATURE
        effective_max_tokens = request.max_tokens if request.max_tokens is not None else AnthropicConfig.MAX_TOKENS

        tools = self._convert_tools(request.tools) if request.tools else None

        system = request.system or ""
        messages = request.messages

        # Handle cache control for supported models
        system_prompt: list[TextBlockParam] = []
        if model_id in AnthropicConfig.SUPPORTED_MODELS_WITH_CACHE_CONTROL:
            system_prompt = [TextBlockParam(**{"text": system, "type": "text", "cache_control": {"type": "ephemeral"}})]
            formatted_messages = self._prepare_messages_with_cache_control(messages)
        else:
            system_prompt = [TextBlockParam(text=system, type="text")]
            formatted_messages = [MessageParam(content=msg["content"], role=msg["role"]) for msg in messages]

        try:
            common_kwargs: dict = {
                "messages": formatted_messages,
                "max_tokens": effective_max_tokens,
                "model": model_id,
                "system": system_prompt,
                "stream": True,
                "temperature": effective_temperature,
            }

            if analytics.capture:
                common_kwargs["posthog_distinct_id"] = analytics.distinct_id
                common_kwargs["posthog_trace_id"] = analytics.trace_id or str(uuid.uuid4())
                common_kwargs["posthog_properties"] = analytics.properties or {}
                common_kwargs["posthog_groups"] = analytics.groups or {}

            if tools is not None:
                common_kwargs["tools"] = tools

            if reasoning_on:
                stream = client.messages.create(
                    **common_kwargs,
                    thinking=ThinkingConfigEnabledParam(
                        type="enabled", budget_tokens=AnthropicConfig.MAX_THINKING_TOKENS
                    ),
                )
            else:
                stream = client.messages.create(**common_kwargs)
        except Exception as e:
            logger.exception(f"Anthropic API error: {e}")
            yield StreamChunk(type="error", data={"error": "Anthropic API error"})
            return

        for chunk in stream:
            if chunk.type == "message_start":
                usage = chunk.message.usage
                yield StreamChunk(
                    type="usage",
                    data={
                        "input_tokens": usage.input_tokens or 0,
                        "output_tokens": usage.output_tokens or 0,
                        "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
                        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
                    },
                )

            elif chunk.type == "message_delta":
                yield StreamChunk(
                    type="usage",
                    data={"input_tokens": 0, "output_tokens": chunk.usage.output_tokens or 0},
                )

            elif chunk.type == "content_block_start":
                if chunk.content_block.type == "thinking":
                    yield StreamChunk(type="reasoning", data={"reasoning": chunk.content_block.thinking or ""})
                elif chunk.content_block.type == "redacted_thinking":
                    yield StreamChunk(type="reasoning", data={"reasoning": "[Redacted thinking block]"})
                elif chunk.content_block.type == "text":
                    if chunk.index > 0:
                        yield StreamChunk(type="text", data={"text": "\n"})
                    yield StreamChunk(type="text", data={"text": chunk.content_block.text})
                elif chunk.content_block.type == "tool_use":
                    yield StreamChunk(
                        type="tool_call",
                        data={
                            "id": chunk.content_block.id,
                            "function": {
                                "name": chunk.content_block.name,
                                "arguments": "",
                            },
                        },
                    )

            elif chunk.type == "content_block_delta":
                if chunk.delta.type == "thinking_delta":
                    yield StreamChunk(type="reasoning", data={"reasoning": chunk.delta.thinking})
                elif chunk.delta.type == "text_delta":
                    yield StreamChunk(type="text", data={"text": chunk.delta.text})
                elif chunk.delta.type == "input_json_delta":
                    yield StreamChunk(
                        type="tool_call",
                        data={
                            "id": None,
                            "function": {
                                "name": "",
                                "arguments": chunk.delta.partial_json,
                            },
                        },
                    )

    @staticmethod
    def validate_key(api_key: str) -> tuple[str, str | None]:
        """Validate an Anthropic API key by making a lightweight API call."""
        from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

        if not api_key.startswith("sk-ant-"):
            return (LLMProviderKey.State.INVALID, "Invalid key format (should start with 'sk-ant-')")
        try:
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return (LLMProviderKey.State.OK, None)
        except anthropic.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except anthropic.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except anthropic.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to Anthropic")
        except Exception as e:
            logger.exception(f"Anthropic key validation error: {e}")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def list_models(api_key: str | None = None) -> list[str]:
        """List available Anthropic models."""
        return AnthropicConfig.SUPPORTED_MODELS

    @staticmethod
    def get_api_key() -> str:
        """Get the default API key from settings."""
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in environment or settings")
        return api_key

    def _get_default_api_key(self) -> str:
        return self.get_api_key()

    def _build_analytics_kwargs(self, analytics: AnalyticsContext, client) -> dict:
        """Build PostHog analytics kwargs if using instrumented client."""
        if analytics.capture and isinstance(client, Anthropic):
            return {
                "posthog_distinct_id": analytics.distinct_id,
                "posthog_trace_id": analytics.trace_id or str(uuid.uuid4()),
                "posthog_properties": analytics.properties or {},
                "posthog_groups": analytics.groups or {},
            }
        return {}

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tools to Anthropic format if needed."""
        from products.llm_analytics.backend.providers.formatters.tools_handler import LLMToolsHandler, ToolFormat

        handler = LLMToolsHandler(tools)
        result = handler.convert_to(ToolFormat.ANTHROPIC)
        assert result is not None, "tools must be non-empty when calling _convert_tools"
        return result

    def _prepare_messages_with_cache_control(self, messages: list[dict[str, Any]]) -> list[MessageParam]:
        """Prepare messages with cache control for supported models."""
        user_msg_indices = [i for i, msg in enumerate(messages) if msg["role"] == "user"]
        last_user_msg_index = user_msg_indices[-1] if user_msg_indices else -1
        second_last_msg_user_index = user_msg_indices[-2] if len(user_msg_indices) > 1 else -1

        prepared_messages: list[MessageParam] = []
        for index, message in enumerate(messages):
            if index in [last_user_msg_index, second_last_msg_user_index]:
                if isinstance(message["content"], str):
                    prepared_message = MessageParam(
                        content=[{"type": "text", "text": message["content"], "cache_control": {"type": "ephemeral"}}],
                        role=message["role"],
                    )
                else:
                    content_blocks = []
                    content = list(message["content"])
                    for i, content_block in enumerate(content):
                        if i == len(content) - 1:
                            content_blocks.append(
                                {
                                    **dict(content_block),
                                    "cache_control": {"type": "ephemeral"},
                                }
                            )
                        else:
                            content_blocks.append(dict(content_block))
                    prepared_message = MessageParam(content=content_blocks, role=message["role"])  # type: ignore
            else:
                prepared_message = MessageParam(content=message["content"], role=message["role"])
            prepared_messages.append(prepared_message)

        return prepared_messages
