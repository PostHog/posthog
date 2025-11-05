import json
import uuid
import logging
from collections.abc import Generator

from django.conf import settings

import posthoganalytics
from anthropic.types import MessageParam, TextBlockParam, ThinkingConfigEnabledParam
from posthoganalytics.ai.anthropic import Anthropic

logger = logging.getLogger(__name__)


class AnthropicConfig:
    # these are hardcoded for now, we might experiment with different values
    MAX_TOKENS: int = 8192
    MAX_THINKING_TOKENS: int = 4096
    TEMPERATURE: float = 0

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


class AnthropicProvider:
    def __init__(self, model_id: str):
        posthog_client = posthoganalytics.default_client
        if not posthog_client:
            raise ValueError("PostHog client not found")

        self.client = Anthropic(api_key=self.get_api_key(), posthog_client=posthog_client)
        self.validate_model(model_id)
        self.model_id = model_id

    def validate_model(self, model_id: str) -> None:
        if model_id not in AnthropicConfig.SUPPORTED_MODELS:
            raise ValueError(f"Model {model_id} is not supported")

    @classmethod
    def get_api_key(cls) -> str:
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in environment or settings")
        return api_key

    def prepare_messages_with_cache_control(self, messages: list[MessageParam]) -> list[MessageParam]:
        """
        Prepare messages with cache control for supported models.
        Marks the latest and second-to-last user messages as ephemeral.
        """
        user_msg_indices = [i for i, msg in enumerate(messages) if msg["role"] == "user"]
        last_user_msg_index = user_msg_indices[-1] if user_msg_indices else -1
        second_last_msg_user_index = user_msg_indices[-2] if len(user_msg_indices) > 1 else -1

        prepared_messages: list[MessageParam] = []
        for index, message in enumerate(messages):
            if index in [last_user_msg_index, second_last_msg_user_index]:
                # Handle both string content and list of content blocks
                if isinstance(message["content"], str):
                    prepared_message = MessageParam(
                        content=[{"type": "text", "text": message["content"], "cache_control": {"type": "ephemeral"}}],
                        role=message["role"],
                    )
                else:
                    # Handle content that's already a list of blocks
                    content_blocks = []
                    content = list(message["content"])  # Convert iterable to list for len()
                    for i, content_block in enumerate(content):
                        if i == len(content) - 1:
                            # Add cache control to the last block
                            content_blocks.append(
                                {
                                    **dict(content_block),  # Convert to dict for unpacking
                                    "cache_control": {"type": "ephemeral"},
                                }
                            )
                        else:
                            content_blocks.append(dict(content_block))  # Convert to dict
                    prepared_message = MessageParam(content=content_blocks, role=message["role"])  # type: ignore
            else:
                prepared_message = MessageParam(content=message["content"], role=message["role"])
            prepared_messages.append(prepared_message)

        return prepared_messages

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
    ) -> Generator[str, None]:
        """
        Async generator function that yields SSE formatted data
        """
        self.validate_model(self.model_id)

        if "3-7" in self.model_id and thinking:
            reasoning_on = True
        else:
            reasoning_on = False

        # Resolve runtime overrides or fall back to config defaults
        effective_temperature = temperature if temperature is not None else AnthropicConfig.TEMPERATURE
        effective_max_tokens = max_tokens if max_tokens is not None else AnthropicConfig.MAX_TOKENS

        # Handle cache control for supported models
        system_prompt: list[TextBlockParam] = []
        if self.model_id in AnthropicConfig.SUPPORTED_MODELS_WITH_CACHE_CONTROL:
            system_prompt = [TextBlockParam(**{"text": system, "type": "text", "cache_control": {"type": "ephemeral"}})]
            formatted_messages = self.prepare_messages_with_cache_control(messages)
        else:
            system_prompt = [TextBlockParam(**{"text": system, "type": "text", "cache_control": None})]
            formatted_messages = [MessageParam(content=msg["content"], role=msg["role"]) for msg in messages]

        try:
            # Build common kwargs
            common_kwargs = {
                "messages": formatted_messages,
                "max_tokens": effective_max_tokens,
                "model": self.model_id,
                "system": system_prompt,
                "stream": True,
                "temperature": effective_temperature,
                "posthog_distinct_id": distinct_id,
                "posthog_trace_id": trace_id or str(uuid.uuid4()),
                "posthog_properties": {**(properties or {}), "ai_product": "playground"},
                "posthog_groups": groups or {},
            }

            # Add tools if provided
            if tools is not None:
                common_kwargs["tools"] = tools

            if reasoning_on:
                stream = self.client.messages.create(  # type: ignore[call-overload]
                    **common_kwargs,
                    thinking=ThinkingConfigEnabledParam(
                        type="enabled", budget_tokens=AnthropicConfig.MAX_THINKING_TOKENS
                    ),
                )
            else:
                stream = self.client.messages.create(  # type: ignore[call-overload]
                    **common_kwargs,
                )
        except Exception as e:
            logger.exception(f"Anthropic API error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': f'Anthropic API error'})}\n\n"
            return

        for chunk in stream:
            if chunk.type == "message_start":
                usage = chunk.message.usage
                yield f"data: {json.dumps({'type': 'usage', 'input_tokens': usage.input_tokens or 0, 'output_tokens': usage.output_tokens or 0, 'cache_writes': getattr(usage, 'cache_creation_input_tokens', None), 'cache_reads': getattr(usage, 'cache_read_input_tokens', None)})}\n\n"

            elif chunk.type == "message_delta":
                yield f"data: {json.dumps({'type': 'usage', 'input_tokens': 0, 'output_tokens': chunk.usage.output_tokens or 0})}\n\n"

            elif chunk.type == "content_block_start":
                if chunk.content_block.type == "thinking":
                    yield f"data: {json.dumps({'type': 'reasoning', 'reasoning': chunk.content_block.thinking or ''})}\n\n"
                elif chunk.content_block.type == "redacted_thinking":
                    yield f"data: {json.dumps({'type': 'reasoning', 'reasoning': '[Redacted thinking block]'})}\n\n"
                elif chunk.content_block.type == "text":
                    if chunk.index > 0:
                        data = json.dumps({"type": "text", "text": "\n"})
                        yield f"data: {data}\n\n"
                    yield f"data: {json.dumps({'type': 'text', 'text': chunk.content_block.text})}\n\n"
                elif chunk.content_block.type == "tool_use":
                    # Start of a tool call
                    tool_call_data = {
                        "type": "tool_call",
                        "id": chunk.content_block.id,
                        "function": {
                            "name": chunk.content_block.name,
                            "arguments": "",  # Will be filled by deltas
                        },
                    }
                    yield f"data: {json.dumps(tool_call_data)}\n\n"

            elif chunk.type == "content_block_delta":
                if chunk.delta.type == "thinking_delta":
                    yield f"data: {json.dumps({'type': 'reasoning', 'reasoning': chunk.delta.thinking})}\n\n"
                elif chunk.delta.type == "text_delta":
                    yield f"data: {json.dumps({'type': 'text', 'text': chunk.delta.text})}\n\n"
                elif chunk.delta.type == "input_json_delta":
                    # Tool call arguments delta
                    tool_call_data = {
                        "type": "tool_call",
                        "id": None,  # We don't have the ID in deltas
                        "function": {
                            "name": "",  # We don't have the name in deltas
                            "arguments": chunk.delta.partial_json,
                        },
                    }
                    yield f"data: {json.dumps(tool_call_data)}\n\n"
