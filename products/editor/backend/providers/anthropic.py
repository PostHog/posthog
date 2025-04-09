import json
from collections.abc import Generator
from django.conf import settings
import anthropic
from anthropic.types import MessageParam, TextBlockParam, ThinkingConfigEnabledParam
from typing import Any
import logging

logger = logging.getLogger(__name__)


class AnthropicConfig:
    # these are hardcoded for now, we might experiment with different values
    MAX_TOKENS: int = 8192
    MAX_THINKING_TOKENS: int = 4096
    TEMPERATURE: float = 0

    SUPPORTED_MODELS: list[str] = [
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307",
    ]

    SUPPORTED_MODELS_WITH_CACHE_CONTROL: list[str] = [
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307",
    ]

    SUPPORTED_MODELS_WITH_THINKING: list[str] = ["claude-3-7-sonnet-20250219"]


class AnthropicProvider:
    def __init__(self, model_id: str):
        self.client = anthropic.Anthropic(api_key=self.get_api_key())
        self.validate_model(model_id)
        self.model_id = model_id

    def validate_model(self, model_id: str) -> None:
        if model_id not in AnthropicConfig.SUPPORTED_MODELS:
            raise ValueError(f"Model {model_id} is not supported")

    def validate_messages(self, messages: list[dict[str, Any]]) -> None:
        if not messages:
            raise ValueError("Messages list cannot be empty")
        for msg in messages:
            if "role" not in msg or "content" not in msg:
                raise ValueError("Each message must contain 'role' and 'content' fields")

    @classmethod
    def get_api_key(cls) -> str:
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in environment or settings")
        return api_key

    def prepare_messages_with_cache_control(self, messages: list[dict[str, Any]]) -> list[MessageParam]:
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
                    prepared_message = {
                        **message,
                        "content": [
                            {"type": "text", "text": message["content"], "cache_control": {"type": "ephemeral"}}
                        ],
                    }
                else:
                    # Handle content that's already a list of blocks
                    content_blocks = []
                    for i, content_block in enumerate(message["content"]):
                        if i == len(message["content"]) - 1:
                            # Add cache control to the last block
                            content_blocks.append({**content_block, "cache_control": {"type": "ephemeral"}})
                        else:
                            content_blocks.append(content_block)
                    prepared_message = {**message, "content": content_blocks}
            else:
                prepared_message = message
            prepared_messages.append(MessageParam(content=prepared_message["content"], role=prepared_message["role"]))

        return prepared_messages

    def stream_response(
        self, system: str, messages: list[dict[str, Any]], thinking: bool = False
    ) -> Generator[str, None]:
        """
        Async generator function that yields SSE formatted data
        """
        self.validate_model(self.model_id)

        if "3-7" in self.model_id and thinking:
            reasoning_on = True
        else:
            reasoning_on = False

        # Handle cache control for supported models
        system_prompt: list[TextBlockParam] = []
        if self.model_id in AnthropicConfig.SUPPORTED_MODELS_WITH_CACHE_CONTROL:
            system_prompt = [TextBlockParam(**{"text": system, "type": "text", "cache_control": {"type": "ephemeral"}})]
            formatted_messages = self.prepare_messages_with_cache_control(messages)
        else:
            system_prompt = [TextBlockParam(**{"text": system, "type": "text", "cache_control": None})]
            formatted_messages = [MessageParam(content=msg["content"], role=msg["role"]) for msg in messages]
        try:
            if reasoning_on:
                stream = self.client.messages.create(
                    messages=formatted_messages,
                    max_tokens=AnthropicConfig.MAX_TOKENS,
                    model=self.model_id,
                    system=system_prompt,
                    stream=True,
                    temperature=AnthropicConfig.TEMPERATURE,
                    thinking=ThinkingConfigEnabledParam(
                        type="enabled", budget_tokens=AnthropicConfig.MAX_THINKING_TOKENS
                    ),
                )
            else:
                stream = self.client.messages.create(
                    messages=formatted_messages,
                    max_tokens=AnthropicConfig.MAX_TOKENS,
                    model=self.model_id,
                    system=system_prompt,
                    stream=True,
                    temperature=AnthropicConfig.TEMPERATURE,
                )
        except anthropic.APIError as e:
            logger.exception(f"Anthropic API error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': f'Anthropic API error'})}\n\n"
            return
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': f'Unexpected error'})}\n\n"
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

            elif chunk.type == "content_block_delta":
                if chunk.delta.type == "thinking_delta":
                    yield f"data: {json.dumps({'type': 'reasoning', 'reasoning': chunk.delta.thinking})}\n\n"
                elif chunk.delta.type == "text_delta":
                    yield f"data: {json.dumps({'type': 'text', 'text': chunk.delta.text})}\n\n"
