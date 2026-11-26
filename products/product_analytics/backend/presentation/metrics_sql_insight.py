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
# A SQL insight has no interval or dashboard variables to fill these in.
_METRICS_ONLY_REFERENCE = re.compile(r"\{interval(_seconds)?\}|(?<![\w.'\"`])\$\{?[A-Za-z_]")


def sql_insight_for_metrics_sql(team: Team, query: dict[str, Any]) -> dict[str, Any] | None:
    if query.get("kind") != "MetricsQuery" or query.get("language") != "sql":
        return None
    sql = query.get("sql")
    if not isinstance(sql, str) or _METRICS_ONLY_REFERENCE.search(sql):
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
                query=sql.replace("{date_from}", "{filters.dateRange.from}").replace(
                    "{date_to}", "{filters.dateRange.to}"
                ),
                filters=HogQLFilters(
                    dateRange=DateRange.model_validate(query.get("dateRange") or {"date_from": DEFAULT_DATE_FROM})
                ),
            ),
            display=_DISPLAY.get(str(display_type), ChartDisplayType.ACTIONS_LINE_GRAPH),
        ).model_dump(exclude_none=True, mode="json")
    except ValidationError:
        return None
