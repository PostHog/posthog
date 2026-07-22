"""DRF views for engineering_analytics.

Named, typed read endpoints over the curated PR/CI query builders, one module per surface area,
composed here into the single ``EngineeringAnalyticsViewSet`` (one URL space, one OpenAPI tag).
Shared parameters, query-param helpers, and error degradation live in ``_base``.
"""

from drf_spectacular.utils import extend_schema

from products.engineering_analytics.backend.presentation.views._base import (
    ENGINEERING_ANALYTICS_TAG,
    EngineeringAnalyticsViewSetBase,
)
from products.engineering_analytics.backend.presentation.views.ci_signals import CISignalsConfigMixin
from products.engineering_analytics.backend.presentation.views.pull_requests import PullRequestActionsMixin
from products.engineering_analytics.backend.presentation.views.sources import SourcesMixin
from products.engineering_analytics.backend.presentation.views.suite_health import TestHealthActionsMixin
from products.engineering_analytics.backend.presentation.views.teams import TeamActionsMixin
from products.engineering_analytics.backend.presentation.views.workflows import WorkflowActionsMixin


@extend_schema(tags=[ENGINEERING_ANALYTICS_TAG])
class EngineeringAnalyticsViewSet(
    SourcesMixin,
    CISignalsConfigMixin,
    PullRequestActionsMixin,
    WorkflowActionsMixin,
    TestHealthActionsMixin,
    TeamActionsMixin,
    EngineeringAnalyticsViewSetBase,
):
    """PR and CI lifecycle analytics over the GitHub warehouse data."""

    # Grouped by mixin; TestScopeEnrollment asserts this stays in lockstep with the actions.
    scope_object_read_actions = [
        # sources
        "sources",
        # ci_signals
        "ci_signals_config",
        # pull_requests
        "ci_cards",
        "pull_requests",
        "pr_lifecycle",
        "resolve_branch",
        "pr_runs",
        "ci_failure_logs",
        "pr_cost",
        "author_workflow_costs",
        # workflows
        "workflow_health",
        "workflow_run",
        "workflow_runs",
        "workflow_run_activity",
        "workflow_runner_costs",
        "workflow_jobs",
        "repo_overview",
        "current_branch_health",
        "repo_run_activity",
        "master_failures",
        "run_failure_logs",
        "job_aggregates",
        # test_health
        "flaky_tests",
        "broken_tests",
        "quarantine",
        # teams
        "team_ci_health",
        "team_ci_activity",
        "team_merge_trend",
    ]
    scope_object_write_actions: list[str] = ["quarantine_request", "update_ci_signals_config"]
