"""
Facade re-exports for product analytics HogQL query runners.

Core's query-runner registry (``posthog/hogql_queries/query_runner.py``) dispatches
on query ``kind`` and constructs these runners by class identity; the paths_v2
presentation imports the segment-to-funnels helpers. The implementations stay in
``backend/hogql_queries/`` (the wiring location, covered by the contract-check
inputs). Runner modules pull the heavy HogQL import chain, so — like
warehouse_sources' pipeline facade — names resolve lazily (PEP 562), keeping the
runners off the ``django.setup()`` path that presentation loads at startup.
"""

_B = "products.product_analytics.backend.hogql_queries."

_LAZY = {
    "PATHS_V2_OTHER": "paths_v2.path_item",
    "PathsQueryRunner": "paths.paths_query_runner",
    "PathsV2QueryRunner": "paths_v2.paths_v2_query_runner",
    "StickinessQueryRunner": "stickiness.stickiness_query_runner",
    "anchored_segment_to_funnels_query": "paths_v2.funnel_converter",
    "edge_to_funnels_query": "paths_v2.funnel_converter",
    "item_label": "paths_v2.path_item",
    "resolve_step_sources": "paths_v2.path_item",
    "step_source_for_event": "paths_v2.path_item",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
