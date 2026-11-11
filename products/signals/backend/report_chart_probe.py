"""Write-time probe for report charts: run each Trends chart once and find the ones with no data.

Kept apart from `report_charts.py`, which must stay free of the query stack (see its docstring).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import structlog

from posthog.schema import ChartDisplayType

from posthog.clickhouse.query_tagging import tag_queries
from posthog.models import Team

from products.product_analytics.backend.facade.queries import run_cached_trends_query
from products.signals.backend.report_charts import ReportChart

logger = structlog.get_logger(__name__)

# The whole probe for one report write. A chart that does not fit is not probed, never refused.
CHART_PROBE_TIME_BUDGET_SECONDS = 20.0
CHART_PROBE_QUERY_TIMEOUT_SECONDS = 10
# Lets a reader who opens the report soon after it lands reuse the probe's result.
CHART_PROBE_CACHE_AGE_SECONDS = 15 * 60
# Displays the reader renders through their own runner, so a plain Trends run measures other data.
_OWN_RUNNER_DISPLAYS = frozenset(
    {ChartDisplayType.BOX_PLOT, ChartDisplayType.CALENDAR_HEATMAP, ChartDisplayType.SLOPE_GRAPH}
)


def empty_trends_chart_ids(team: Team, charts: Sequence[ReportChart]) -> list[str]:
    """The ids of the Trends charts whose query returns no series, or only zeros.

    Best effort: a chart that is not a Trends chart, a query that fails, and a chart past the time
    budget all count as not empty, so the probe can refuse only a chart it saw return nothing.
    """
    deadline = time.monotonic() + CHART_PROBE_TIME_BUDGET_SECONDS
    empty: list[str] = []
    for chart in charts:
        source = _trends_source(chart.query)
        if source is None:
            continue
        remaining = deadline - time.monotonic()
        if remaining < 1:
            break
        try:
            tag_queries(trigger="signals_report_chart_probe")
            response = run_cached_trends_query(
                query=source,
                team=team,
                max_execution_time_seconds=min(CHART_PROBE_QUERY_TIMEOUT_SECONDS, int(remaining)),
                cache_age_seconds=CHART_PROBE_CACHE_AGE_SECONDS,
            )
        except Exception:
            logger.warning("signals_report_chart_probe_failed", team_id=team.id, chart_id=chart.chart_id, exc_info=True)
            continue
        if not any(_series_has_data(series) for series in response.results):
            empty.append(chart.chart_id)
    return empty


def _trends_source(query: dict[str, Any]) -> dict[str, Any] | None:
    if query.get("kind") != "InsightVizNode":
        return None
    source = query.get("source")
    if not isinstance(source, dict) or source.get("kind") != "TrendsQuery":
        return None
    trends_filter = source.get("trendsFilter")
    if isinstance(trends_filter, dict) and trends_filter.get("display") in _OWN_RUNNER_DISPLAYS:
        return None
    return source


def _series_has_data(series: dict[str, Any]) -> bool:
    return any(series.get("data") or ()) or bool(series.get("aggregated_value"))
