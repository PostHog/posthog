"""Framework-only dispatch adapter for Error tracking query runners.

This module exists *only* so that the central HogQL dispatch in
``posthog.hogql_queries.query_runner.get_query_runner`` can construct
Error tracking runners without reaching into product-internal modules.
It is **not** a business facade surface and should not be used by
non-framework code.

New cross-product callers should use :func:`query_issues` in
``products.error_tracking.backend.facade.api`` instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.models.team.team import Team


_ERROR_TRACKING_QUERY_KINDS: frozenset[str] = frozenset(
    {
        "ErrorTrackingQuery",
        "ErrorTrackingIssueCorrelationQuery",
        "ErrorTrackingSimilarIssuesQuery",
        "ErrorTrackingBreakdownsQuery",
    }
)


def is_error_tracking_query_kind(kind: str) -> bool:
    """Return True if the given query kind is owned by Error tracking."""
    return kind in _ERROR_TRACKING_QUERY_KINDS


def build_query_runner(
    *,
    kind: str,
    query: Any,
    team: Team,
    timings: Any = None,
    modifiers: Any = None,
    limit_context: Any = None,
) -> Any:
    """Construct an Error tracking query runner for the given query kind.

    Lazily imports the concrete runner class so framework code never needs
    to know which product module it lives in.
    """
    if kind == "ErrorTrackingQuery":
        from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner

        return ErrorTrackingQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ErrorTrackingIssueCorrelationQuery":
        from products.error_tracking.backend.hogql_queries.error_tracking_issue_correlation_query_runner import (
            ErrorTrackingIssueCorrelationQueryRunner,
        )

        return ErrorTrackingIssueCorrelationQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ErrorTrackingSimilarIssuesQuery":
        from products.error_tracking.backend.hogql_queries.error_tracking_similar_issues_query_runner import (
            ErrorTrackingSimilarIssuesQueryRunner,
        )

        return ErrorTrackingSimilarIssuesQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ErrorTrackingBreakdownsQuery":
        from products.error_tracking.backend.hogql_queries.error_tracking_breakdowns_query_runner import (
            ErrorTrackingBreakdownsQueryRunner,
        )

        return ErrorTrackingBreakdownsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    raise ValueError(f"Unknown Error tracking query kind: {kind!r}")


__all__ = [
    "build_query_runner",
    "is_error_tracking_query_kind",
]
