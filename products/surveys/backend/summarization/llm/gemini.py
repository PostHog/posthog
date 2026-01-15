"""Gemini provider for survey summarization."""

from dataclasses import dataclass

from rest_framework import exceptions

from products.surveys.backend.llm import generate_structured_output

from ..constants import DEFAULT_MODEL
from ..models import GeminiModel
from .schema import SurveySummaryResponse


@dataclass
class SummarizationResult:
    """Result of survey summarization including trace_id for feedback mapping."""

    summary: SurveySummaryResponse
    trace_id: str


SYSTEM_PROMPT = """You are a product manager's assistant specializing in analyzing survey responses.

Your goal is to identify actionable user pain points and needs from survey data.

Guidelines:
- Be concise and focus on what matters most for product decisions
- Identify patterns and themes across responses (maximum 5 themes)
- Use actual quotes to support your analysis
- Prioritize themes by how frequently they appear
- For each theme, estimate the percentage of responses that mention it (>50%, 25-50%, 10-25%, or <10%)
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
) -> SummarizationResult:
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
        SummarizationResult with summary and trace_id for feedback mapping
    """
    if not responses:
        raise exceptions.ValidationError("responses cannot be empty")

    summary, trace_id = generate_structured_output(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(question_text, responses),
        response_schema=SurveySummaryResponse,
        posthog_properties={
            "survey_id": survey_id,
            "question_id": question_id,
            "response_count": len(responses),
            "ai_product": "survey_summary",
        },
        team_id=team_id,
        distinct_id=distinct_id,
    )

    return SummarizationResult(summary=summary, trace_id=trace_id)
