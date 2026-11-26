"""Saves a SQL metrics insight that reads other tables as a SQL insight.

The metrics path runs SQL over the metrics tables only, so such an insight would fail every time it runs.
"""

import re
from typing import Any

from pydantic import ValidationError

from posthog.schema import ChartDisplayType, DataVisualizationNode, DateRange, HogQLFilters, HogQLQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.metrics import tables_outside_metrics
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select

from posthog.models import Team

# A metrics insight defaults to the last 24 hours.
DEFAULT_DATE_FROM = "-24h"

_DISPLAY: dict[str, ChartDisplayType] = {
    "line": ChartDisplayType.ACTIONS_LINE_GRAPH,
    "area": ChartDisplayType.ACTIONS_AREA_GRAPH,
    "bar": ChartDisplayType.ACTIONS_BAR,
    "stat": ChartDisplayType.BOLD_NUMBER,
    "gauge": ChartDisplayType.BOLD_NUMBER,
    "bargauge": ChartDisplayType.ACTIONS_BAR,
    "table": ChartDisplayType.ACTIONS_TABLE,
}
# A SQL insight has no interval to fill these in.
_INTERVAL_PLACEHOLDER = re.compile(r"\{\s*interval(_seconds)?\s*\}")
_DATE_PLACEHOLDERS = {
    re.compile(r"\{\s*date_from\s*\}"): "{filters.dateRange.from}",
    re.compile(r"\{\s*date_to\s*\}"): "{filters.dateRange.to}",
}
# A dashboard variable reference, as metrics SQL reads it. `properties.$browser` is a field, not a reference.
_VARIABLE_REFERENCE = re.compile(r"(?<![\w.])(?P<quote>['\"`]?)\$\{?(?P<name>[A-Za-z_][A-Za-z0-9_]*)")


def _uses_dashboard_variables(sql: str, variables: Any) -> bool:
    """Whether metrics SQL would fill in a variable. It leaves a quoted reference to an unknown variable as text."""
    names = set(variables) if isinstance(variables, dict) else set()
    return any(not match.group("quote") or match.group("name") in names for match in _VARIABLE_REFERENCE.finditer(sql))


def sql_insight_for_metrics_sql(team: Team, query: dict[str, Any]) -> dict[str, Any] | None:
    if query.get("kind") != "MetricsQuery" or query.get("language") != "sql":
        return None
    sql = query.get("sql")
    if (
        not isinstance(sql, str)
        or _INTERVAL_PLACEHOLDER.search(sql)
        or _uses_dashboard_variables(sql, query.get("variables"))
    ):
        return None
    try:
        parsed = parse_select(
            sql, placeholders={"date_from": ast.Constant(value=None), "date_to": ast.Constant(value=None)}
        )
        context = HogQLContext(
            team_id=team.pk, team=team, database=Database.create_for(team=team), enable_select_queries=True
        )
        if not tables_outside_metrics(parsed, context):
            return None
    except BaseHogQLError:
        return None
    display = query.get("display")
    display_type = display.get("type") if isinstance(display, dict) else None
    try:
        return DataVisualizationNode(
            source=HogQLQuery(
                query=_with_filter_placeholders(sql),
                filters=HogQLFilters(
                    dateRange=DateRange.model_validate(query.get("dateRange") or {"date_from": DEFAULT_DATE_FROM})
                ),
            ),
            display=_DISPLAY.get(str(display_type), ChartDisplayType.ACTIONS_LINE_GRAPH),
        ).model_dump(exclude_none=True, mode="json")
    except ValidationError:
        return None


def _with_filter_placeholders(sql: str) -> str:
    for placeholder, replacement in _DATE_PLACEHOLDERS.items():
        sql = placeholder.sub(replacement, sql)
    return sql
