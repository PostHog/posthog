"""Gemini provider for survey summarization."""

import uuid

from django.conf import settings

import structlog
import posthoganalytics
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai
from rest_framework import exceptions

from ..constants import DEFAULT_MODEL
from ..models import GeminiModel
from .schema import SurveySummaryResponse

logger = structlog.get_logger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Get or create the Gemini client singleton with PostHog analytics."""
    global _client
    if _client is None:
        posthog_client = posthoganalytics.default_client
        _client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            posthog_client=posthog_client,
        )
    return _client


SYSTEM_PROMPT = """You are a product manager's assistant specializing in analyzing survey responses.

Your goal is to identify actionable user pain points and needs from survey data.

Guidelines:
- Be concise and focus on what matters most for product decisions
- Identify patterns and themes across responses (maximum 5 themes)
- Use actual quotes to support your analysis
- Prioritize themes by how frequently they appear
- Focus on actionable insights that can drive product improvements
- Keep the overview to 1-2 sentences
- Keep the key insight to 1 sentence"""


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
    *,
    distinct_id: str | None = None,
    survey_id: str | None = None,
    question_id: str | None = None,
    team_id: int | None = None,
) -> SurveySummaryResponse:
    """
    Generate survey summary using Gemini API with structured outputs.

    Args:
        question_text: The survey question being summarized
        responses: List of response strings to analyze
        model: Gemini model to use
        distinct_id: User's distinct ID for analytics
        survey_id: Survey ID for analytics
        question_id: Question ID for analytics
        team_id: Team ID for analytics

    Returns:
        Structured survey summary response
    """
    if not responses:
        raise exceptions.ValidationError("responses cannot be empty")

    client = _get_client()

    config = GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=SurveySummaryResponse.model_json_schema(),
    )

    trace_id = str(uuid.uuid4())

    try:
        response = client.models.generate_content(
            model=model,
            contents=_build_user_prompt(question_text, responses),
            config=config,
            posthog_distinct_id=distinct_id or "",
            posthog_trace_id=trace_id,
            posthog_properties={
                "survey_id": survey_id,
                "question_id": question_id,
                "response_count": len(responses),
                "ai_product": "survey_summary",
            },
            posthog_groups={"project": str(team_id)} if team_id else {},
        )

        if not response.text:
            raise exceptions.ValidationError("Gemini returned empty response")

        return SurveySummaryResponse.model_validate_json(response.text)

    except exceptions.ValidationError:
        raise
    except Exception:
        logger.exception("Gemini API call failed for survey summary")
        raise exceptions.APIException("Failed to generate summary")
