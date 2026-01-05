"""Main entry point for survey summarization."""

from ..constants import DEFAULT_MODEL
from ..models import GeminiModel
from .gemini import SummarizationResult, summarize_with_gemini


def summarize_responses(
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
    Generate AI-powered summary of survey responses.

    Args:
        question_text: The survey question being summarized
        responses: List of response strings to analyze
        model: LLM model to use
        distinct_id: User's distinct ID for analytics
        survey_id: Survey ID for analytics
        question_id: Question ID for analytics
        team_id: Team ID for analytics

    Returns:
        SummarizationResult with summary and trace_id for feedback mapping
    """
    return summarize_with_gemini(
        question_text,
        responses,
        model,
        distinct_id=distinct_id,
        survey_id=survey_id,
        question_id=question_id,
        team_id=team_id,
    )
