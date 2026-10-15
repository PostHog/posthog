from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
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


@frozen
class CircleciInsightsEndpointConfig:
    name: str
    # Path template relative to the API base; {slug} is the project slug (or org slug for
    # org-level endpoints) and {workflow_name} is filled per workflow during fan-out.
    path: str
    # Composite by default: Insights rows are aggregates keyed by name within a project (and
    # workflow), not globally unique ids, so most keys include the injected parent identifiers.
    primary_keys: list[str]
    # Stable timestamp field for datetime partitioning. Only the row-level tables carry one;
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
    # Whether the endpoint accepts branch filtering (the branch / all-branches params). Note the
    # time-series endpoints take a single `branch` name but no `all-branches`, so they stay off.
    takes_branch_params: bool = False
    # Whether the endpoint accepts the server-side `start-date` filter used for incremental sync.
    takes_start_date: bool = False
    # Whether `start-date` needs the full RFC 3339 timestamp. The runs endpoint accepts the
    # date-only form; the time-series endpoint is only documented for a timestamp.
    start_date_needs_timestamp: bool = False
    # Fixed query params the endpoint always needs.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Row order the API returns. The row-level listings declare desc, which defers the
    # incremental watermark commit to the end of the sync — see the per-endpoint comments.
    sort_mode: SortMode = "asc"
    should_sync_default: bool = True


CIRCLECI_INSIGHTS_ENDPOINTS: dict[str, CircleciInsightsEndpointConfig] = {
    "workflow_metrics": CircleciInsightsEndpointConfig(
        name="workflow_metrics",
        path="/insights/{slug}/workflows",
        primary_keys=["project_slug", "name"],
        takes_reporting_window=True,
        takes_branch_params=True,
    ),
    "workflow_summary": CircleciInsightsEndpointConfig(
        name="workflow_summary",
        path="/insights/{slug}/workflows/{workflow_name}/summary",
        primary_keys=["project_slug", "workflow_name"],
        fan_out_workflows=True,
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
        takes_start_date=True,
        sort_mode="desc",
    ),
    "job_metrics": CircleciInsightsEndpointConfig(
        name="job_metrics",
        path="/insights/{slug}/workflows/{workflow_name}/jobs",
        primary_keys=["project_slug", "workflow_name", "name"],
        fan_out_workflows=True,
        takes_reporting_window=True,
        takes_branch_params=True,
    ),
    "job_timeseries": CircleciInsightsEndpointConfig(
        name="job_timeseries",
        path="/insights/time-series/{slug}/workflows/{workflow_name}/jobs",
        # One bucket per job per interval, so the interval timestamp is part of the row identity.
        primary_keys=["project_slug", "workflow_name", "name", "timestamp"],
        partition_key="timestamp",
        # The endpoint takes a server-side `start-date` filter, so incremental sync genuinely
        # narrows what is fetched. The bucket timestamp never moves once emitted.
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        fan_out_workflows=True,
        takes_start_date=True,
        start_date_needs_timestamp=True,
        # Hourly buckets are only retained for 48 hours, which a scheduled sync cannot rely on;
        # daily buckets match the ~90-day retention the rest of the source works against.
        extra_params={"granularity": "daily"},
        # The endpoint documents no row order. Desc defers the watermark commit to the end of the
        # sync, which is correct whichever order the API returns.
        sort_mode="desc",
    ),
    "flaky_tests": CircleciInsightsEndpointConfig(
        name="flaky_tests",
        path="/insights/{slug}/flaky-tests",
        # A test is reported once per (workflow, job) it flakes in; the test identity is
        # classname + test_name, neither of which is unique on its own.
        primary_keys=["project_slug", "workflow_name", "job_name", "classname", "test_name"],
    ),
    "workflow_test_metrics": CircleciInsightsEndpointConfig(
        name="workflow_test_metrics",
        path="/insights/{slug}/workflows/{workflow_name}/test-metrics",
        # A test is reported per job it runs in, and neither classname nor test name is unique
        # on its own.
        primary_keys=["project_slug", "workflow_name", "job_name", "classname", "test_name"],
        fan_out_workflows=True,
        takes_branch_params=True,
    ),
    "branches": CircleciInsightsEndpointConfig(
        name="branches",
        path="/insights/{slug}/branches",
        primary_keys=["project_slug", "branch"],
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
