import os
import json
from collections.abc import Generator
from django.conf import settings
import openai
from anthropic.types import MessageParam
import logging

from products.editor.backend.providers.formatters.openai_formatter import convert_to_openai_messages

logger = logging.getLogger(__name__)


class InkeepConfig:
    SUPPORTED_MODELS = ["inkeep-qa-expert"]


class InkeepProvider:
    def __init__(self, model_id: str):
        self.client = openai.OpenAI(base_url="https://api.inkeep.com/v1", api_key=self.get_api_key())
        if model_id not in InkeepConfig.SUPPORTED_MODELS:
            raise ValueError(f"Model {model_id} is not supported")
        self.model_id = model_id

    @classmethod
    def get_api_key(cls) -> str:
        api_key = os.environ.get("INKEEP_API_KEY") or settings.INKEEP_API_KEY
        if not api_key:
            raise ValueError("INKEEP_API_KEY is not set in environment or settings")
        return api_key

    def stream_response(
        self, system: str, messages: list[MessageParam], thinking: bool = False
    ) -> Generator[str, None, None]:
        """
        Generator function that yields SSE formatted data
        """

        try:
            stream = self.client.chat.completions.create(
                model=self.model_id,
                stream=True,
                messages=convert_to_openai_messages(messages),
                stream_options={"include_usage": True},
            )
        except openai.APIError as e:
            logger.exception(f"Inkeep API error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Inkeep API error'})}\n\n"
            return
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Unexpected error'})}\n\n"
            return

        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield f"data: {json.dumps({'type': 'text', 'text': delta.content})}\n\n"
            if chunk.usage:
                yield f"data: {json.dumps({'type': 'usage', 'input_tokens': chunk.usage.prompt_tokens or 0, 'output_tokens': chunk.usage.completion_tokens or 0})}\n\n"
