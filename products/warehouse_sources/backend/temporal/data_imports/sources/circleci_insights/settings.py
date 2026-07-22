from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Reporting windows the Insights aggregate endpoints accept. CircleCI retains Insights data
# for roughly 90 days, so last-90-days is both the default and the maximum coverage.
REPORTING_WINDOWS = (
    "last-24-hours",
    "last-7-days",
    "last-30-days",
    "last-60-days",
    "last-90-days",
)
DEFAULT_REPORTING_WINDOW = "last-90-days"


@dataclass
class CircleciInsightsEndpointConfig:
    name: str
    # Path template relative to the API base; {slug} is the project slug (or org slug for
    # org-level endpoints) and {workflow_name} is filled per workflow during fan-out.
    path: str
    # Composite by default: Insights rows are aggregates keyed by name within a project (and
    # workflow), not globally unique ids, so most keys include the injected parent identifiers.
    primary_keys: list[str]
    # Stable creation-time field for datetime partitioning. Only workflow_runs rows carry one;
    # the aggregate tables are rolling-window snapshots with no stable per-row timestamp.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Fan-out endpoints are fetched once per workflow name discovered from the project's
    # workflow metrics listing.
    fan_out_workflows: bool = False
    # Whether the endpoint accepts the reporting-window query param.
    takes_reporting_window: bool = False
    # Org-level endpoints iterate the org slugs derived from the configured project slugs
    # (vcs/org/repo -> vcs/org) instead of the project slugs themselves.
    org_level: bool = False
    # Whether the endpoint accepts branch filtering (branch / all-branches params).
    takes_branch_params: bool = False
    should_sync_default: bool = True


CIRCLECI_INSIGHTS_ENDPOINTS: dict[str, CircleciInsightsEndpointConfig] = {
    "workflow_metrics": CircleciInsightsEndpointConfig(
        name="workflow_metrics",
        path="/insights/{slug}/workflows",
        primary_keys=["project_slug", "name"],
        takes_reporting_window=True,
        takes_branch_params=True,
    ),
    "workflow_runs": CircleciInsightsEndpointConfig(
        name="workflow_runs",
        path="/insights/{slug}/workflows/{workflow_name}",
        # Workflow run ids are UUIDs, unique across projects and workflows.
        primary_keys=["id"],
        partition_key="created_at",
        # The runs endpoint honors a server-side start-date filter (verified with a live
        # probe: start-date drops older runs from the response), so incremental sync
        # genuinely reduces the data fetched. Rows come back newest-first.
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        fan_out_workflows=True,
        takes_branch_params=True,
    ),
    "job_metrics": CircleciInsightsEndpointConfig(
        name="job_metrics",
        path="/insights/{slug}/workflows/{workflow_name}/jobs",
        primary_keys=["project_slug", "workflow_name", "name"],
        fan_out_workflows=True,
        takes_reporting_window=True,
        takes_branch_params=True,
    ),
    "flaky_tests": CircleciInsightsEndpointConfig(
        name="flaky_tests",
        path="/insights/{slug}/flaky-tests",
        # A test is reported once per (workflow, job) it flakes in; the test identity is
        # classname + test_name, neither of which is unique on its own.
        primary_keys=["project_slug", "workflow_name", "job_name", "classname", "test_name"],
    ),
    "org_summary_metrics": CircleciInsightsEndpointConfig(
        name="org_summary_metrics",
        path="/insights/{slug}/summary",
        primary_keys=["org_slug", "project_name"],
        takes_reporting_window=True,
        org_level=True,
        # The org summary endpoint requires org membership (it 401s without auth, so its
        # response shape could not be verified against the live API) and may be plan-gated.
        # Off by default so a fresh source doesn't enable a table whose first sync may 403.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(CIRCLECI_INSIGHTS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CIRCLECI_INSIGHTS_ENDPOINTS.items() if config.incremental_fields
}
