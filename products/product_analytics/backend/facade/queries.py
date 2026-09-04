"""
Facade re-exports for product analytics HogQL query runners.

Core's query-runner registry (``posthog/hogql_queries/query_runner.py``) dispatches
on query ``kind`` and constructs these runners by class identity; the paths_v2
presentation imports the segment-to-funnels helpers. The implementations stay in
``backend/hogql_queries/`` (the wiring location, which stays out of the
contract-check inputs while no test outside the product drives it). Runner modules
pull the heavy HogQL import chain, so — like warehouse_sources' pipeline facade —
names resolve lazily (PEP 562), keeping the runners off the ``django.setup()`` path
that presentation loads at startup.
"""

from typing import TYPE_CHECKING

_B = "products.product_analytics.backend.hogql_queries."

_LAZY = {
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
    "TrendsQueryRunner": "trends.trends_query_runner",
    "anchored_segment_to_funnels_query": "paths_v2.funnel_converter",
    "edge_to_funnels_query": "paths_v2.funnel_converter",
    "item_label": "paths_v2.path_item",
    "resolve_step_sources": "paths_v2.path_item",
    "step_source_for_event": "paths_v2.path_item",
}

__all__ = sorted(_LAZY)


if TYPE_CHECKING:
    # Static view for mypy and IDEs only; runtime resolves through __getattr__ below, so these
    # modules stay off the django.setup() path. The runners that other products subclass must
    # resolve to their real class here, or subclass attribute inference collapses to Any. Ruff
    # cannot see the __getattr__ use, so each import carries an F401 guard.
    from products.product_analytics.backend.hogql_queries.trends.boxplot_trends_query_runner import (  # noqa: F401
        BoxPlotTrendsQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.calendar_heatmap_query_runner import (  # noqa: F401
        CalendarHeatmapQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.calendar_heatmap_trends_query_runner import (  # noqa: F401
        CalendarHeatmapTrendsQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.slope_graph_trends_query_runner import (  # noqa: F401
        SlopeGraphTrendsQueryRunner,
    )
    from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import (  # noqa: F401
        TrendsQueryRunner,
    )


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
