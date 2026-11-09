"""Write-time probe for report charts: run each Trends chart once and find the ones with no data.

A chart query is checked for its shape when a scout writes it, not for whether it matches anything.
A filter that can never match (a regex escaped one level too deep, a property value with the wrong
case) stores without complaint and then draws an empty chart for every reader. The probe runs the
query once, through the same cached Trends path the report metrics use, so the author learns about
the empty chart while it can still fix it.

Kept apart from `report_charts.py`, which must stay free of the query stack (see its docstring).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import structlog

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
    return source


def _series_has_data(series: dict[str, Any]) -> bool:
    data = series.get("data")
    values = [*(data if isinstance(data, list) else []), series.get("aggregated_value"), series.get("count")]
    return any(isinstance(value, int | float) and not isinstance(value, bool) and value != 0 for value in values)
