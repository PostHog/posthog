import json
import uuid
import logging
from collections.abc import Generator

from django.conf import settings

import posthoganalytics
from anthropic.types import MessageParam
from google.genai import Client as DefaultClient
from google.genai.errors import APIError
from google.genai.types import Blob, Content, GenerateContentConfig, Part, VideoMetadata
from posthoganalytics.ai.gemini import genai

from products.llm_analytics.backend.providers.formatters.gemini_formatter import convert_anthropic_messages_to_gemini

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

    SUPPORTED_VIDEO_MIME_TYPES: list[str] = [
        "video/x-flv",
        "video/quicktime",
        "video/mpeg",
        "video/mpegs",
        "video/mpg",
        "video/mp4",
        "video/webm",
        "video/wmv",
        "video/3gpp",
    ]

    VIDEO_MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20MB


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

    def _extract_content_from_chunk(self, chunk) -> list[str]:
        results = []

        if hasattr(chunk, "text") and chunk.text:
            results.append(f"data: {json.dumps({'type': 'text', 'text': chunk.text})}\n\n")

            return results

        if hasattr(chunk, "candidates") and chunk.candidates:
            for candidate in chunk.candidates:
                if hasattr(candidate, "content") and candidate.content:
                    if hasattr(candidate.content, "parts") and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, "function_call") and part.function_call:
                                tool_call_data = {
                                    "type": "tool_call",
                                    "id": f"gemini_tool_{hash(str(part.function_call))}",
                                    "function": {
                                        "name": part.function_call.name,
                                        "arguments": (
                                            json.dumps(dict(part.function_call.args))
                                            if part.function_call.args
                                            else "{}"
                                        ),
                                    },
                                }

                                results.append(f"data: {json.dumps(tool_call_data)}\n\n")
                            elif hasattr(part, "text") and part.text:
                                results.append(f"data: {json.dumps({'type': 'text', 'text': part.text})}\n\n")

        return results

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
            if tools is not None:
                config_kwargs["tools"] = tools

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
                content_messages = self._extract_content_from_chunk(chunk)

                yield from content_messages

                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
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

    async def understand_video(
        self,
        video_bytes: bytes,
        mime_type: str,
        prompt: str,
        start_offset_s: int | None = None,
        end_offset_s: int | None = None,
        trace_id: str | None = None,
    ) -> str | None:
        """
        Understand a video and return a summary using the provided prompt
        https://ai.google.dev/gemini-api/docs/video-understanding
        """
        self.validate_model(self.model_id)
        # Workaroud to make async working, as PostHog wrapper doesn't support async yet
        client = DefaultClient(api_key=self.get_api_key())
        if mime_type not in GeminiConfig.SUPPORTED_VIDEO_MIME_TYPES:
            logger.exception(f"Video bytes for understanding video are not in a supported MIME type: {mime_type}")
            return None
        if not len(video_bytes):
            logger.exception(f"Video bytes for understanding video are empty")
            return None
        if len(video_bytes) > GeminiConfig.VIDEO_MAX_SIZE_BYTES:
            logger.exception(f"Video bytes for understanding video are too large")
            return None
        try:
            video_part_config = {"inline_data": Blob(data=video_bytes, mime_type=mime_type)}
            video_metadata_config = {}
            if start_offset_s:
                video_metadata_config["start_offset"] = f"{start_offset_s}s"
            if end_offset_s:
                video_metadata_config["end_offset"] = f"{end_offset_s}s"
            if video_metadata_config:
                video_part_config["video_metadata"] = VideoMetadata(**video_metadata_config)
            video_part = Part(**video_part_config)
            prompt_part = Part(text=prompt)
            contents = Content(parts=[video_part, prompt_part])
            response = await client.aio.models.generate_content(
                model=self.model_id,
                contents=contents,
                # TODO: Add trace ID, when PostHog wrapper supports async
            )
            return response.text
        except APIError as e:
            logger.exception(f"Gemini API error while understanding video: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error while understanding video: {e}")
            return None
