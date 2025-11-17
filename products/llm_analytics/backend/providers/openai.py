import json
import uuid
import logging
from collections.abc import Generator
from typing import Any

from django.conf import settings

import posthoganalytics
from anthropic.types import MessageParam
from openai.types import CompletionUsage, ReasoningEffort
from openai.types.chat import ChatCompletionDeveloperMessageParam, ChatCompletionSystemMessageParam
from posthoganalytics.ai.openai import OpenAI

from products.llm_analytics.backend.providers.formatters.openai_formatter import convert_to_openai_messages

logger = logging.getLogger(__name__)


class OpenAIConfig:
    # these are hardcoded for now, we might experiment with different values
    REASONING_EFFORT: ReasoningEffort = "medium"
    TEMPERATURE: float = 0

    SUPPORTED_MODELS: list[str] = [
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "o4-mini",
        "o3-mini",
        "o3",
        "o3-pro",
        "o4-mini",
        "gpt-4o",
        "gpt-4o-mini",
        # GPT-5 series identifiers
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
    ]

    SUPPORTED_MODELS_WITH_THINKING: list[str] = [
        "o3",
        "o3-pro",
        "o4-mini",
        "o3-mini",
        # GPT-5 and GPT-5-mini support reasoning effort levels
        "gpt-5",
        "gpt-5-mini",
    ]


class OpenAIProvider:
    def __init__(self, model_id: str):
        posthog_client = posthoganalytics.default_client
        if not posthog_client:
            raise ValueError("PostHog client not found")

        self.client = OpenAI(
            api_key=self.get_api_key(), posthog_client=posthog_client, base_url=settings.OPENAI_BASE_URL
        )
        self.validate_model(model_id)
        self.model_id = model_id

    def validate_model(self, model_id: str) -> None:
        if model_id not in OpenAIConfig.SUPPORTED_MODELS:
            raise ValueError(f"Model {model_id} is not supported")

    @classmethod
    def get_api_key(cls) -> str:
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in environment or settings")
        return api_key

    def yield_usage(self, usage: CompletionUsage) -> Generator[str, None]:
        input_tokens = usage.prompt_tokens or 0
        output_tokens = usage.completion_tokens or 0
        cache_read_tokens = (
            usage.prompt_tokens_details.cached_tokens
            if usage.prompt_tokens_details and usage.prompt_tokens_details.cached_tokens is not None
            else 0
        )
        cache_write_tokens = 0
        non_cached_input_tokens = max(0, input_tokens - cache_read_tokens - cache_write_tokens)

        yield f"data: {json.dumps({'type': 'usage', 'input_tokens': non_cached_input_tokens, 'output_tokens': output_tokens, 'cache_read_tokens': cache_read_tokens, 'cache_write_tokens': cache_write_tokens})}\n\n"

    def stream_response(
        self,
        system: str,
        messages: list[MessageParam],
        thinking: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
        distinct_id: str = "",
        trace_id: str | None = None,
        properties: dict | None = None,
        groups: dict | None = None,
        reasoning_level: str | None = None,
    ) -> Generator[str, None]:
        """
        Async generator function that yields SSE formatted data
        """
        self.validate_model(self.model_id)

        supports_reasoning = self.model_id in OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING
        reasoning_on = supports_reasoning and (thinking or bool(reasoning_level))

        try:
            effective_temperature = temperature if temperature is not None else OpenAIConfig.TEMPERATURE

            def build_common_kwargs() -> dict[str, Any]:
                common: dict[str, Any] = {
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "posthog_distinct_id": distinct_id,
                    "posthog_trace_id": trace_id or str(uuid.uuid4()),
                    "posthog_properties": {**(properties or {}), "ai_product": "playground"},
                    "posthog_groups": groups or {},
                }
                # Don't include temperature for reasoning models as they don't support it
                if self.model_id not in OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING:
                    common["temperature"] = effective_temperature
                if max_tokens is not None:
                    common["max_completion_tokens"] = max_tokens
                if tools is not None:
                    common["tools"] = tools
                return common

            if supports_reasoning:
                # Determine reasoning effort: explicit level wins; fallback to default when thinking is on
                selected_effort: ReasoningEffort | None = None
                if reasoning_level in ("minimal", "low", "medium", "high"):
                    selected_effort = reasoning_level  # type: ignore[assignment]
                elif reasoning_on:
                    selected_effort = OpenAIConfig.REASONING_EFFORT
                stream = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        ChatCompletionDeveloperMessageParam(
                            {
                                "role": "developer",
                                "content": system,
                            }
                        ),
                        *convert_to_openai_messages(messages),
                    ],
                    reasoning_effort=selected_effort,
                    **build_common_kwargs(),
                )
            else:
                stream = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        ChatCompletionSystemMessageParam(
                            {
                                "role": "system",
                                "content": system,
                            }
                        ),
                        *convert_to_openai_messages(messages),
                    ],
                    **build_common_kwargs(),
                )

            for chunk in stream:
                if len(chunk.choices) > 0:
                    choice = chunk.choices[0]

                    # Handle regular text content
                    if choice.delta.content:
                        yield f"data: {json.dumps({'type': 'text', 'text': choice.delta.content})}\n\n"

                    # Handle tool calls
                    if choice.delta.tool_calls:
                        for tool_call in choice.delta.tool_calls:
                            tool_call_data = {
                                "type": "tool_call",
                                "id": tool_call.id,
                                "function": {
                                    "name": tool_call.function.name if tool_call.function.name else "",
                                    "arguments": tool_call.function.arguments if tool_call.function.arguments else "",
                                },
                            }
                            yield f"data: {json.dumps(tool_call_data)}\n\n"

                if chunk.usage:
                    yield from self.yield_usage(chunk.usage)

        except Exception as e:
            logger.exception(f"OpenAI API error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': f'{e}'})}\n\n"
            return
