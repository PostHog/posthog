"""Gemini provider for LLM summarization."""

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google import genai
from google.genai.types import GenerateContentConfig
from rest_framework import exceptions

from ..models import GeminiModel, SummarizationMode
from ..utils import load_summarization_template
from .schema import SummarizationResponse

logger = structlog.get_logger(__name__)


def _summarize_sync(
    text_repr: str,
    team_id: int,
    mode: SummarizationMode,
    model: GeminiModel,
) -> SummarizationResponse:
    """Generate summary using Gemini API with structured outputs (sync version)."""
    if not text_repr:
        raise exceptions.ValidationError("text_repr cannot be empty")

    system_prompt = load_summarization_template(f"prompts/system_{mode}.djt", {})
    user_prompt = load_summarization_template("prompts/user.djt", {"text_repr": text_repr})

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    config = GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0,
        response_mime_type="application/json",
        response_json_schema=SummarizationResponse.model_json_schema(),
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=config,
        )

        if not response.text:
            raise exceptions.ValidationError("Gemini returned empty response")
        return SummarizationResponse.model_validate_json(response.text)
    except exceptions.ValidationError:
        raise
    except Exception as e:
        logger.exception("Gemini API call failed", error=str(e), team_id=team_id, model=model)
        raise exceptions.APIException("Failed to generate summary due to an internal error")


async def summarize_with_gemini(
    text_repr: str,
    team_id: int,
    mode: SummarizationMode,
    model: GeminiModel,
) -> SummarizationResponse:
    """Generate summary using Gemini API with structured outputs."""
    return await sync_to_async(_summarize_sync, thread_sensitive=False)(text_repr, team_id, mode, model)
