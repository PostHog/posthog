"""Main entry point for survey summarization."""

from ..constants import DEFAULT_MODEL
from ..models import GeminiModel
from .gemini import summarize_with_gemini
from .schema import SurveySummaryResponse


def summarize_responses(
    question_text: str,
    responses: list[str],
    model: GeminiModel = DEFAULT_MODEL,
) -> SurveySummaryResponse:
    """
    Generate AI-powered summary of survey responses.

    Args:
        question_text: The survey question being summarized
        responses: List of response strings to analyze
        model: LLM model to use

    Returns:
        Structured survey summary with themes and insights
    """
    return summarize_with_gemini(question_text, responses, model)
