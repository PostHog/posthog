import os
import json
from collections.abc import Generator
from django.conf import settings
import openai
from typing import Any


class InkeepConfig:
    SUPPORTED_MODELS = ["inkeep-qa"]


class InkeepProvider:
    def __init__(self, model_id: str):
        self.client = openai.OpenAI(base_url="https://api.inkeep.com/v1", api_key=self.get_api_key())
        self.model_id = model_id

    def validate_messages(self, messages: list[dict[str, Any]]) -> None:
        if not messages:
            raise ValueError("Messages list cannot be empty")
        for msg in messages:
            if "role" not in msg or "content" not in msg:
                raise ValueError("Each message must contain 'role' and 'content' fields")

    @classmethod
    def get_api_key(cls) -> str:
        api_key = os.environ.get("INKEEP_API_KEY") or settings.INKEEP_API_KEY
        if not api_key:
            raise ValueError("INKEEP_API_KEY is not set in environment or settings")
        return api_key

    def stream_response(self, _: str, messages: list, thinking: bool = False) -> Generator[str, None, None]:
        """
        Generator function that yields SSE formatted data
        """
        self.validate_messages(messages)

        try:
            stream = self.client.chat.completions.create(
                model=self.model_id, stream=True, messages=messages, stream_options={"include_usage": True}
            )
        except openai.APIError as e:
            yield f"data: {json.dumps({'type': 'error', 'error': f'Inkeep API error: {str(e)}'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': f'Unexpected error: {str(e)}'})}\n\n"

        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield f"data: {json.dumps({'type': 'text', 'text': delta.content})}\n\n"
            if chunk.usage:
                yield f"data: {json.dumps({'type': 'usage', 'input_tokens': chunk.usage.prompt_tokens or 0, 'output_tokens': chunk.usage.completion_tokens or 0})}\n\n"
