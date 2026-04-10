from importlib import import_module
from typing import Any

__all__ = [
    "ErrorTrackingBreakdownsQueryRunner",
    "ErrorTrackingIssueCorrelationQueryRunner",
    "ErrorTrackingQueryRunner",
    "ErrorTrackingSimilarIssuesQueryRunner",
    "ErrorTrackingWeeklyDigestProjectContract",
    "ErrorTrackingIssueAssignmentContract",
    "ErrorTrackingIssueContract",
    "ErrorTrackingIssueFingerprintContract",
    "SearchErrorTrackingIssuesTool",
    "TeamCountContract",
    "aget_issue",
    "aget_issue_first_event",
    "aquery_issues",
    "auto_select_project_for_user",
    "build_ingestion_failures_url",
    "build_remote_config",
    "compute_week_over_week_change",
    "count_issues_created_since",
    "count_issues_for_team",
    "delete_issue_fingerprints",
    "get_client_safe_suppression_rules",
    "get_crash_free_sessions",
    "get_daily_exception_counts",
    "get_exception_counts",
    "get_exception_summary_for_team",
    "get_issue",
    "get_issue_assignment",
    "get_issue_by_fingerprint",
    "get_issue_fingerprint",
    "get_issue_first_event",
    "get_issue_counts_by_team",
    "iter_issue_fingerprints_created_between",
    "get_new_issues_for_team",
    "get_org_ids_with_exceptions",
    "get_symbol_set_counts_by_team",
    "get_top_issues_for_team",
    "get_weekly_digest_projects_for_organization",
    "has_resolved_issues",
    "publish_issue_fingerprint_override",
    "query_issues",
    "update_issue_fingerprint_first_seen_and_version",
]

_CONTRACT_EXPORTS = {
    "ErrorTrackingWeeklyDigestProjectContract",
    "ErrorTrackingIssueAssignmentContract",
    "ErrorTrackingIssueContract",
    "ErrorTrackingIssueFingerprintContract",
    "TeamCountContract",
}

_MODULE_EXPORTS = {
    "ErrorTrackingBreakdownsQueryRunner": (
        "products.error_tracking.backend.hogql_queries.error_tracking_breakdowns_query_runner",
        "ErrorTrackingBreakdownsQueryRunner",
    ),
    "ErrorTrackingIssueCorrelationQueryRunner": (
        "products.error_tracking.backend.hogql_queries.error_tracking_issue_correlation_query_runner",
        "ErrorTrackingIssueCorrelationQueryRunner",
    ),
    "ErrorTrackingQueryRunner": (
        "products.error_tracking.backend.hogql_queries.error_tracking_query_runner",
        "ErrorTrackingQueryRunner",
    ),
    "ErrorTrackingSimilarIssuesQueryRunner": (
        "products.error_tracking.backend.hogql_queries.error_tracking_similar_issues_query_runner",
        "ErrorTrackingSimilarIssuesQueryRunner",
    ),
    "SearchErrorTrackingIssuesTool": (
        "products.error_tracking.backend.tools.search_issues",
        "SearchErrorTrackingIssuesTool",
    ),
}


def __getattr__(name: str) -> Any:
    if name in _CONTRACT_EXPORTS:
        return getattr(import_module("products.error_tracking.backend.facade.contracts"), name)
    if name in _MODULE_EXPORTS:
        module_name, export_name = _MODULE_EXPORTS[name]
        return getattr(import_module(module_name), export_name)
    if name in __all__:
        return getattr(import_module("products.error_tracking.backend.facade.api"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
