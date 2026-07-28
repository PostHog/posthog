"""HogQL-backed input source for the score lab classifier: an alternative to the
archived-Harmonic-fetch payload path (see enrichment/labels.py) when a config sets
EnrichmentPromptConfig.input_query instead of input_fields.

Every failure here surfaces as InputQueryError, which the API maps to a 400 - a staff user's
typo in a query box is bad input, not a server fault.
"""

from typing import Any

from django.conf import settings

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import BaseHogQLError, ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.errors import ExposedCHQueryError
from posthog.models.team import Team


class InputQueryError(ValueError):
    """A HogQL input_query failed to parse, wasn't a SELECT statement, or failed to execute."""


def parse_input_query(query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    """Syntax-only validation for save/run: parses but never executes. Raises
    InputQueryError with a clean message on a syntax error or a non-SELECT statement."""
    try:
        node = parse_select(query)
    except BaseHogQLError as e:
        raise InputQueryError(f"Invalid HogQL query: {e}") from e
    if not isinstance(node, (ast.SelectQuery, ast.SelectSetQuery)):
        raise InputQueryError("input_query must be a SELECT statement")
    return node


def rows_from_query_result(columns: list[str] | None, results: list[Any] | None) -> list[dict[str, Any]]:
    """Pure mapping from a HogQLQueryResponse's columns/results into one dict per row, keyed
    by column name. Split out from run_input_query so the row-mapping contract is testable
    without touching ClickHouse."""
    if not columns or not results:
        return []
    return [dict(zip(columns, row)) for row in results]


def run_input_query(query: str, limit: int, *, team_id: int | None = None) -> list[dict[str, Any]]:
    """Parse, execute against team_id (defaults to settings.SCORE_LAB_HOGQL_TEAM_ID), and map
    to one dict per row.

    The limit is pushed onto the query rather than applied to the results: slicing afterwards
    would still materialize every row the query asked for in the web process.
    """
    node = parse_input_query(query)
    resolved_team_id = team_id if team_id is not None else settings.SCORE_LAB_HOGQL_TEAM_ID
    try:
        team = Team.objects.get(id=resolved_team_id)
    except Team.DoesNotExist as e:
        raise InputQueryError(f"Score lab HogQL team {resolved_team_id} does not exist.") from e

    # A SelectSetQuery (a UNION) has no single limit to set; the LimitContext ceiling still
    # caps it, and the slice below is the backstop.
    if isinstance(node, ast.SelectQuery):
        node.limit = ast.Constant(value=limit)

    try:
        with tags_context(product=Product.GROWTH, feature=Feature.QUERY, team_id=team.id):
            response = execute_hogql_query(
                node,
                team=team,
                query_type="GrowthScoreLabInputQuery",
                limit_context=LimitContext.POSTHOG_AI,
            )
    except (ExposedHogQLError, ExposedCHQueryError) as e:
        raise InputQueryError(f"Query failed: {e}") from e

    rows = rows_from_query_result(response.columns, response.results)
    return rows[:limit]
