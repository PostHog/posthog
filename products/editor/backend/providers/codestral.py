"""
ViewSet for IDE Proxy
"""

import logging
import json
from collections.abc import Generator
from django.conf import settings
import mistralai

logger = logging.getLogger(__name__)


class CodestralConfig:
    # these are hardcoded for now, we might experiment with different values
    MAX_TOKENS = 4096
    TEMPERATURE = 0
    TOP_P = 1

    SUPPORTED_MODELS = ["codestral-latest"]


class CodestralProvider:
    def __init__(self, model_id: str):
        self.client = mistralai.Mistral(api_key=self.get_api_key())
        self.validate_model(model_id)
        self.model_id = model_id

    def validate_model(self, model_id: str) -> None:
        if model_id not in CodestralConfig.SUPPORTED_MODELS:
            raise ValueError(f"Model {model_id} is not supported")

    @classmethod
    def get_api_key(cls) -> str:
        api_key = settings.MISTRAL_API_KEY
        if not api_key:
            raise ValueError("MISTRAL_API_KEY is not set in environment or settings")
        return api_key

    def stream_fim_response(self, prompt: str, suffix: str, stop: list[str]) -> Generator[str, None, None]:
        """
        Generator function that yields SSE formatted data
        """

        try:
            response = self.client.fim.stream(
                model=self.model_id,
                prompt=prompt,
                suffix=suffix,
                temperature=CodestralConfig.TEMPERATURE,
                top_p=CodestralConfig.TOP_P,
                stop=stop,
            )
            for chunk in response:
                data = chunk.data.choices[0].delta.content
                yield f"data: {json.dumps({'type': 'text', 'text': data})}\n\n"
        except Exception as e:
            logger.exception(f"Codestral API error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Codestral API error'})}\n\n"
