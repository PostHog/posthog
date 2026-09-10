"""
Facade re-exports for product analytics HogQL query runners.

Core's query-runner registry (``posthog/hogql_queries/query_runner.py``) dispatches
on query ``kind`` and constructs these runners by class identity; the paths_v2
presentation imports the segment-to-funnels helpers. The implementations stay in
``backend/hogql_queries/`` (the wiring location; the ``trends/`` subtree stays in the
contract-check inputs while tests outside the product drive it). Runner modules
pull the heavy HogQL import chain, so — like warehouse_sources' pipeline facade —
names resolve lazily (PEP 562), keeping the runners off the ``django.setup()`` path
that presentation loads at startup.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from products.product_analytics.backend.facade.contracts import TrendsQueryRunResult

_B = "products.product_analytics.backend.hogql_queries."

_LAZY = {
    "ALLOWED_SESSION_MATH_PROPERTIES": "trends.aggregation_operations",
    "PATHS_V2_OTHER": "paths_v2.path_item",
    "BoxPlotTrendsQueryRunner": "trends.boxplot_trends_query_runner",
    "CalendarHeatmapQueryRunner": "trends.calendar_heatmap_query_runner",
    "CalendarHeatmapTrendsQueryRunner": "trends.calendar_heatmap_trends_query_runner",
    "FunnelCorrelationQueryRunner": "funnels.funnel_correlation_query_runner",
    "FunnelsQueryRunner": "funnels.funnels_query_runner",
    "LifecycleQueryRunner": "lifecycle.lifecycle_query_runner",
    "PathsQueryRunner": "paths.paths_query_runner",
    "RetentionQueryRunner": "retention.retention_query_runner",
    "PathsV2QueryRunner": "paths_v2.paths_v2_query_runner",
    "SlopeGraphTrendsQueryRunner": "trends.slope_graph_trends_query_runner",
    "StickinessQueryRunner": "stickiness.stickiness_query_runner",
    "TrendsDisplay": "trends.display",
    "TrendsQueryRunner": "trends.trends_query_runner",
    "anchored_segment_to_funnels_query": "paths_v2.funnel_converter",
    "edge_to_funnels_query": "paths_v2.funnel_converter",
    "get_properties_chain": "trends.utils",
    "item_label": "paths_v2.path_item",
    "resolve_step_sources": "paths_v2.path_item",
    "step_source_for_event": "paths_v2.path_item",
}

__all__ = sorted((*_LAZY, "run_cached_trends_query"))


if TYPE_CHECKING:
    from posthog.models import Team

    # Static view for mypy and IDEs only; runtime resolves through __getattr__ below, so these
    # modules stay off the django.setup() path. The runners that other products subclass must
    # resolve to their real class here, or subclass attribute inference collapses to Any. Ruff
    # cannot see the __getattr__ use, so each import carries an F401 guard.
    from products.product_analytics.backend.hogql_queries.trends.aggregation_operations import (  # noqa: F401
        ALLOWED_SESSION_MATH_PROPERTIES,
    )
    from products.product_analytics.backend.hogql_queries.trends.boxplot_trends_query_runner import (  # noqa: F401
        BoxPlotTrendsQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.calendar_heatmap_query_runner import (  # noqa: F401
        CalendarHeatmapQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.calendar_heatmap_trends_query_runner import (  # noqa: F401
        CalendarHeatmapTrendsQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.display import TrendsDisplay  # noqa: F401
    from products.product_analytics.backend.hogql_queries.trends.slope_graph_trends_query_runner import (  # noqa: F401
        SlopeGraphTrendsQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import (  # noqa: F401
        TrendsQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.utils import get_properties_chain  # noqa: F401


def run_cached_trends_query(
    *, query: dict[str, Any], team: Team, max_execution_time_seconds: int, cache_age_seconds: int
) -> TrendsQueryRunResult:
    """Run a Trends query through the blocking recent-cache path."""

    from posthog.hogql.constants import HogQLGlobalSettings

    from posthog.clickhouse.query_tagging import get_query_tag_value, is_api_key_access_method
    from posthog.hogql_queries.query_runner import ExecutionMode

    from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner

    runner = TrendsQueryRunner(
        query=query,
        team=team,
        hogql_settings=HogQLGlobalSettings(max_execution_time=max_execution_time_seconds),
    )
    runner.is_query_service = is_api_key_access_method(get_query_tag_value("access_method"))
    response = runner.run(
        execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        cache_age_seconds=cache_age_seconds,
    )
    results = getattr(response, "results", None)
    if not isinstance(results, list) or any(not isinstance(result, dict) for result in results):
        raise ValueError("Trends query returned an invalid result set")
    last_refresh = getattr(response, "last_refresh", None)
    return TrendsQueryRunResult(
        results=results,
        last_refresh=last_refresh if isinstance(last_refresh, datetime) else None,
    )


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
