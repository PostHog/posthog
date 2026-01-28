"""Fetch survey responses for summarization."""

from datetime import datetime
from typing import cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team


def fetch_responses(
    survey_id: str,
    question_index: int | None,
    question_id: str | None,
    start_date: datetime,
    end_date: datetime,
    team: Team,
    limit: int = 100,
    exclude_values: list[str] | None = None,
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

    Returns:
        List of response strings
    """
    paginator = HogQLHasMorePaginator(limit=limit, offset=0)
    q = parse_select(
        """
        SELECT getSurveyResponse({question_index}, {question_id})
        FROM events
        WHERE event == 'survey sent'
            AND properties.$survey_id = {survey_id}
            AND trim(getSurveyResponse({question_index}, {question_id})) != ''
            AND timestamp >= {start_date}
            AND timestamp <= {end_date}
        """,
        {
            "survey_id": ast.Constant(value=survey_id),
            "start_date": ast.Constant(value=start_date),
            "end_date": ast.Constant(value=end_date),
            "question_index": ast.Constant(value=question_index),
            "question_id": ast.Constant(value=question_id),
        },
    )

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

    return responses
