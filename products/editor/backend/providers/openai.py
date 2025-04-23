import json
from collections.abc import Generator
from django.conf import settings
import openai
from anthropic.types import MessageParam
from openai.types import ReasoningEffort, CompletionUsage
from openai.types.chat import (
    ChatCompletionDeveloperMessageParam,
    ChatCompletionSystemMessageParam,
)
import logging

from products.editor.backend.providers.formatters.openai_formatter import convert_to_openai_messages

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
        "o1",
        "o1-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "chatgpt-4o-latest",
    ]

    SUPPORTED_MODELS_WITH_THINKING: list[str] = [
        "o3",
        "o4-mini",
        "o3-mini",
        "o1",
        "o1-mini",
        "o1-preview",
    ]


class OpenAIProvider:
    def __init__(self, model_id: str):
        self.client = openai.OpenAI(api_key=self.get_api_key())
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
        self, system: str, messages: list[MessageParam], thinking: bool = False
    ) -> Generator[str, None]:
        """
        Async generator function that yields SSE formatted data
        """
        self.validate_model(self.model_id)

        if self.model_id in OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING and thinking:
            reasoning_on = True
        else:
            reasoning_on = False

        try:
            if self.model_id in OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING:
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
                    stream=True,
                    stream_options={"include_usage": True},
                    reasoning_effort=OpenAIConfig.REASONING_EFFORT if reasoning_on else None,
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
                    stream=True,
                    stream_options={"include_usage": True},
                    temperature=OpenAIConfig.TEMPERATURE,
                )

            for chunk in stream:
                if len(chunk.choices) > 0:
                    if chunk.choices[0].delta.content:
                        yield f"data: {json.dumps({'type': 'text', 'text': chunk.choices[0].delta.content})}\n\n"
                if chunk.usage:
                    yield from self.yield_usage(chunk.usage)

        except openai.APIError as e:
            logger.exception(f"OpenAI API error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': f'OpenAI API error'})}\n\n"
            return
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': f'Unexpected error'})}\n\n"
            return
