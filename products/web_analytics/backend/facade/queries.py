"""Query-runner surface of the web_analytics facade.

Core's HogQL query-runner registry reaches web_analytics by importing the
runner classes; registry consumers dispatch on class identity, so re-export
the classes as-is. The runner *modules* (`web_overview`, `stats_table`) are
re-exported too — `posthog/test/base.py` captures `execute_hogql_query` by
patching them per-module, and that capture must cross the boundary through the
facade like everything else.

This submodule carries HogQL-heavy imports by design. Keep them out of
`facade/api.py` (config-only consumers) and out of `facade/hogql.py` (the
light shared tables) so neither drags the runners onto its import path.
"""

from products.web_analytics.backend.hogql_queries import stats_table, web_overview
from products.web_analytics.backend.hogql_queries.external_clicks import WebExternalClicksTableQueryRunner
from products.web_analytics.backend.hogql_queries.notable_changes import WebNotableChangesQueryRunner
from products.web_analytics.backend.hogql_queries.page_url_search_query_runner import PageUrlSearchQueryRunner
from products.web_analytics.backend.hogql_queries.session_attribution_explorer_query_runner import (
    SessionAttributionExplorerQueryRunner,
)
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_goals import WebGoalsQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner
from products.web_analytics.backend.hogql_queries.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner

__all__ = [
    "PageUrlSearchQueryRunner",
    "SessionAttributionExplorerQueryRunner",
    "WebExternalClicksTableQueryRunner",
    "WebGoalsQueryRunner",
    "WebNotableChangesQueryRunner",
    "WebOverviewQueryRunner",
    "WebStatsTableQueryRunner",
    "WebVitalsPathBreakdownQueryRunner",
    "stats_table",
    "web_overview",
]
