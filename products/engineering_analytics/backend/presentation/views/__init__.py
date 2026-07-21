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
from products.engineering_analytics.backend.presentation.views.pull_requests import PullRequestActionsMixin
from products.engineering_analytics.backend.presentation.views.sources import SourcesMixin
from products.engineering_analytics.backend.presentation.views.teams import TeamActionsMixin
from products.engineering_analytics.backend.presentation.views.test_health import TestHealthActionsMixin
from products.engineering_analytics.backend.presentation.views.workflows import WorkflowActionsMixin


@extend_schema(tags=[ENGINEERING_ANALYTICS_TAG])
class EngineeringAnalyticsViewSet(
    SourcesMixin,
    PullRequestActionsMixin,
    WorkflowActionsMixin,
    TestHealthActionsMixin,
    TeamActionsMixin,
    EngineeringAnalyticsViewSetBase,
):
    """PR and CI lifecycle analytics over the GitHub warehouse data."""

    scope_object_read_actions = [
        "sources",
        "ci_cards",
        "pull_requests",
        "workflow_health",
        "pr_lifecycle",
        "resolve_branch",
        "quarantine",
        "pr_runs",
        "ci_failure_logs",
        "pr_cost",
        "workflow_run",
        "workflow_runs",
        "workflow_run_activity",
        "workflow_runner_costs",
        "author_workflow_costs",
        "workflow_jobs",
        "flaky_tests",
        "broken_tests",
        "repo_overview",
        "repo_run_activity",
        "current_branch_health",
        "master_failures",
        "run_failure_logs",
        "job_aggregates",
    ]
    scope_object_write_actions: list[str] = ["quarantine_request"]
