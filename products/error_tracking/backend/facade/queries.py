"""Facade re-exports for error tracking HogQL query runners.

Core's query-runner registry (``posthog/hogql_queries/query_runner.py``) dispatches
on query ``kind`` and constructs these runners by class identity. Re-exporting the
classes keeps that registry coupling at the facade boundary while the heavy HogQL
imports stay out of ``facade/api.py`` so config-only consumers don't drag them onto
the ``django.setup()`` path.
"""

from typing import Any

from posthog.schema import ErrorTrackingQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team

from products.error_tracking.backend.hogql_queries.error_tracking_breakdowns_query_runner import (
    ErrorTrackingBreakdownsQueryRunner,
)
from products.error_tracking.backend.hogql_queries.error_tracking_issue_correlation_query_runner import (
    ErrorTrackingIssueCorrelationQueryRunner,
)
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner
from products.error_tracking.backend.hogql_queries.error_tracking_similar_issues_query_runner import (
    ErrorTrackingSimilarIssuesQueryRunner,
)

__all__ = [
    "ErrorTrackingBreakdownsQueryRunner",
    "ErrorTrackingIssueCorrelationQueryRunner",
    "ErrorTrackingQueryRunner",
    "ErrorTrackingSimilarIssuesQueryRunner",
    "run_error_tracking_query",
]


def run_error_tracking_query(team: Team, query: ErrorTrackingQuery) -> dict[str, Any]:
    """Execute an ErrorTrackingQuery with product query tagging and return the JSON-dumped response."""
    with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
        return ErrorTrackingQueryRunner(team=team, query=query).calculate().model_dump(mode="json")
