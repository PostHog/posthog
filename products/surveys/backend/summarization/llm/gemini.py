"""Gemini provider for survey summarization."""

from django.conf import settings

import structlog
from google import genai
from google.genai.types import GenerateContentConfig
from rest_framework import exceptions

from ..constants import DEFAULT_MODEL
from ..models import GeminiModel
from .schema import SurveySummaryResponse

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are a product manager's assistant specializing in analyzing survey responses.

Your goal is to identify actionable user pain points and needs from survey data.

Guidelines:
- Be concise and focus on what matters most for product decisions
- Identify patterns and themes across responses
- Use actual quotes to support your analysis
- Prioritize themes by how frequently they appear
- Focus on actionable insights that can drive product improvements"""


def _build_user_prompt(question_text: str, responses: list[str]) -> str:
    """Build the user prompt with question and responses."""
    responses_text = "\n".join(f"- {r}" for r in responses)
    return f"""Analyze these survey responses and identify key themes.

Survey Question: {question_text}

Responses:
{responses_text}

Identify the key themes, patterns, and actionable insights. Include relevant quotes to support each theme."""


def summarize_with_gemini(
    question_text: str,
    responses: list[str],
    model: GeminiModel = DEFAULT_MODEL,
) -> SurveySummaryResponse:
    """
    Generate survey summary using Gemini API with structured outputs.

    Args:
        question_text: The survey question being summarized
        responses: List of response strings to analyze
        model: Gemini model to use

    Returns:
        Structured survey summary response
    """
    if not responses:
        raise exceptions.ValidationError("responses cannot be empty")

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    config = GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=SurveySummaryResponse.model_json_schema(),
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=_build_user_prompt(question_text, responses),
            config=config,
        )

        if not response.text:
            raise exceptions.ValidationError("Gemini returned empty response")

        return SurveySummaryResponse.model_validate_json(response.text)

    except exceptions.ValidationError:
        raise
    except Exception:
        logger.exception("Gemini API call failed for survey summary")
        raise exceptions.APIException("Failed to generate summary")
