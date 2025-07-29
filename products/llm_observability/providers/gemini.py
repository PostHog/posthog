from posthoganalytics.ai.gemini import genai
from google.genai.types import GenerateContentConfig
from google.genai.errors import APIError

import json
from collections.abc import Generator
from django.conf import settings
import posthoganalytics
from anthropic.types import MessageParam
import logging
import uuid

from products.llm_observability.providers.formatters.gemini_formatter import convert_anthropic_messages_to_gemini

logger = logging.getLogger(__name__)


class GeminiConfig:
    # these are hardcoded for now, we might experiment with different values
    TEMPERATURE: float = 0

    SUPPORTED_MODELS: list[str] = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]


class GeminiProvider:
    def __init__(self, model_id: str):
        posthog_client = posthoganalytics.default_client
        if not posthog_client:
            raise ValueError("PostHog client not found")

        self.client = genai.Client(api_key=self.get_api_key(), posthog_client=posthog_client)
        self.validate_model(model_id)
        self.model_id = model_id

    def validate_model(self, model_id: str) -> None:
        if model_id not in GeminiConfig.SUPPORTED_MODELS:
            raise ValueError(f"Model {model_id} is not supported")

    @classmethod
    def get_api_key(cls) -> str:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment or settings")
        return api_key

    def stream_response(
        self,
        system: str,
        messages: list[MessageParam],
        thinking: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        distinct_id: str = "",
        trace_id: str | None = None,
        properties: dict | None = None,
        groups: dict | None = None,
    ) -> Generator[str, None]:
        """
        Async generator function that yields SSE formatted data
        """
        self.validate_model(self.model_id)

        try:
            effective_temperature = temperature if temperature is not None else GeminiConfig.TEMPERATURE
            effective_max_tokens = max_tokens  # May be None; Gemini API uses max_output_tokens

            # Build config with conditionals
            config_kwargs = {
                "system_instruction": system,
                "temperature": effective_temperature,
            }
            if effective_max_tokens is not None:
                config_kwargs["max_output_tokens"] = effective_max_tokens

            response = self.client.models.generate_content_stream(
                model=self.model_id,
                contents=convert_anthropic_messages_to_gemini(messages),
                config=GenerateContentConfig(**config_kwargs),
                posthog_distinct_id=distinct_id,
                posthog_trace_id=trace_id or str(uuid.uuid4()),
                posthog_properties={**(properties or {}), "ai_product": "playground"},
                posthog_groups=groups or {},
            )

            for chunk in response:
                if chunk.text:
                    yield f"data: {json.dumps({'type': 'text', 'text': chunk.text})}\n\n"
                if chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.prompt_token_count
                    output_tokens = chunk.usage_metadata.candidates_token_count
                    yield f"data: {json.dumps({'type': 'usage', 'input_tokens': input_tokens, 'output_tokens': output_tokens})}\n\n"

        except APIError as e:
            logger.exception(f"Gemini API error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': f'Gemini API error'})}\n\n"
            return
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': f'Unexpected error'})}\n\n"
            return
