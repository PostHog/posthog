"""Fetch survey responses for summarization."""

from datetime import datetime
from typing import cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team

MIN_SINGLE_TOKEN_LENGTH_FOR_AI_SUMMARY = 8
MIN_TOTAL_LENGTH_FOR_AI_SUMMARY = 3


def is_substantive_response_for_ai_summary(response: str) -> bool:
    """
    Heuristic filter to reduce low-signal / accidental survey answers in AI summaries.

    This is intentionally conservative: it removes obvious junk (empty/whitespace-only, punctuation-only)
    and very short single-token answers (e.g. "ddsads") that tend to add noise rather than meaning.
    """

    text = response.strip()
    if not text:
        return False

    # Avoid summarizing "x", "ok", etc. These are nearly always low-signal in open text summaries.
    if len(text) < MIN_TOTAL_LENGTH_FOR_AI_SUMMARY:
        return False

    # Ignore answers with no alphanumerics (e.g. "!!!", "…", emoji-only).
    if not any(ch.isalnum() for ch in text):
        return False

    # Drop very short single-token responses (no whitespace) as they're disproportionately accidental/noisy.
    if len(text) < MIN_SINGLE_TOKEN_LENGTH_FOR_AI_SUMMARY and not any(ch.isspace() for ch in text):
        return False

    return True


def fetch_responses(
    survey_id: str,
    question_index: int | None,
    question_id: str | None,
    start_date: datetime,
    end_date: datetime,
    team: Team,
    limit: int = 100,
    exclude_values: list[str] | None = None,
    exclude_uuids: set[str] | None = None,
    filter_for_ai_summary: bool = False,
) -> list[str]:
    """
    Fetch survey responses for a specific question.

    Args:
        survey_id: The survey ID
        question_index: Index of the question (0-based)
        question_id: ID of the question
        start_date: Start date for filtering responses
        end_date: End date for filtering responses
        team: The team to query
        limit: Maximum number of responses to fetch
        exclude_values: List of values to exclude (e.g., predefined choices for choice questions)
        exclude_uuids: Set of response UUIDs to exclude (e.g., archived responses)
        filter_for_ai_summary: If True, drop obvious low-signal responses for AI summarization

    Returns:
        List of response strings
    """
    paginator = HogQLHasMorePaginator(limit=limit, offset=0)

    # Build the base query
    base_query = """
        SELECT getSurveyResponse({question_index}, {question_id})
        FROM events
        WHERE event == 'survey sent'
            AND properties.$survey_id = {survey_id}
            AND trim(getSurveyResponse({question_index}, {question_id})) != ''
            AND timestamp >= {start_date}
            AND timestamp <= {end_date}
    """

    # Add archived response filter if there are UUIDs to exclude
    # UUIDs are pre-validated by Django's UUIDField when stored in SurveyResponseArchive
    if exclude_uuids:
        base_query += " AND uuid NOT IN {exclude_uuids}"

    placeholders: dict[str, ast.Expr] = {
        "survey_id": ast.Constant(value=survey_id),
        "start_date": ast.Constant(value=start_date),
        "end_date": ast.Constant(value=end_date),
        "question_index": ast.Constant(value=question_index),
        "question_id": ast.Constant(value=question_id),
    }

    if exclude_uuids:
        placeholders["exclude_uuids"] = ast.Tuple(exprs=[ast.Constant(value=uuid) for uuid in exclude_uuids])

    q = parse_select(base_query, placeholders)

    query_response = paginator.execute_hogql_query(
        team=team,
        query_type="survey_response_list_query",
        query=cast(ast.SelectQuery, q),
    )

    responses = [x[0] for x in query_response.results if x[0]]

    # Filter out predefined choices for choice questions
    if exclude_values:
        exclude_set = set(exclude_values)
        responses = [r for r in responses if r not in exclude_set]

    if filter_for_ai_summary:
        responses = [r for r in responses if is_substantive_response_for_ai_summary(r)]

    return responses
