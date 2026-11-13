from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

RUN_CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "run_created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "run_created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Signed log-archive URLs on plans and applies. They grant read access to the raw run logs
# without any HCP Terraform authorization, so they must never reach the warehouse.
_LOG_URL_FIELDS = ("log_read_url",)


@dataclass(frozen=False)
class TerraformCloudEndpointConfig:
    name: str
    # Path template. `{organization}` is filled from the source config; fan-out endpoints may
    # also use `{workspace_id}` (filled per workspace).
    path: str
    # Extra query param templates, formatted with the same placeholders as `path` plus
    # `{workspace_name}` (state versions are listed by workspace *name*, not id).
    params: dict[str, str] = field(default_factory=dict)
    # Partition on a STABLE creation timestamp so partitions don't rewrite on every sync.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The API has no server-side updated-since filter. Runs and state versions are returned
    # newest-first by creation time, so incremental sync pages descending and stops once an
    # entire page predates the watermark (see terraform_cloud.py); "desc" tells the pipeline
    # to persist the watermark only at successful job end.
    sort_mode: Literal["asc", "desc"] = "asc"
    # Fan out one paginated request sequence per workspace in the organization.
    fan_out_over_workspaces: bool = False
    # Safety overlap subtracted from the incremental watermark on every run, re-pulling a
    # window of rows that merge dedupes on the primary key. Used for runs, whose
    # status/timestamps keep mutating until the run reaches a final state.
    incremental_lookback: Optional[timedelta] = None
    # Normalized attribute keys stripped from rows before they're yielded. Keeps signed
    # capability URLs (state-file download/upload) out of the warehouse — anyone who can query
    # the table could otherwise read or write raw Terraform state, including its secrets,
    # without any HCP Terraform authorization.
    drop_fields: tuple[str, ...] = ()
    # Plans and applies have no list endpoint. They come from the runs list with this value as
    # `include`, and each row is the included resource that the run's relationship of the same
    # name points at, stamped with run_id and run_created_at.
    run_included_relationship: Optional[str] = None
    # Show-only resources that a workspace points at through this relationship. `path` takes
    # `{resource_id}`, and a workspace whose relationship is empty costs no request.
    workspace_relationship: Optional[str] = None
    # Workspace attribute holding when the related resource last changed. An incremental sync
    # skips the request for a workspace whose value predates the watermark.
    workspace_relationship_updated_at: Optional[str] = None


TERRAFORM_CLOUD_ENDPOINTS: dict[str, TerraformCloudEndpointConfig] = {
    "organizations": TerraformCloudEndpointConfig(
        name="organizations",
        # Scoped to the configured organization only. `/organizations` (no id) returns every
        # organization the token can access, leaking other orgs' names, admin emails, and
        # plan/SSO metadata to anyone who can query this table. The single-resource response is
        # normalized to a one-row list downstream.
        path="/organizations/{organization}",
    ),
    "projects": TerraformCloudEndpointConfig(
        name="projects",
        path="/organizations/{organization}/projects",
    ),
    "teams": TerraformCloudEndpointConfig(
        name="teams",
        path="/organizations/{organization}/teams",
    ),
    "workspaces": TerraformCloudEndpointConfig(
        name="workspaces",
        path="/organizations/{organization}/workspaces",
    ),
    "runs": TerraformCloudEndpointConfig(
        name="runs",
        path="/workspaces/{workspace_id}/runs",
        partition_key="created_at",
        incremental_fields=CREATED_AT_INCREMENTAL_FIELDS,
        sort_mode="desc",
        fan_out_over_workspaces=True,
        # A run's status/status-timestamps mutate after creation until it reaches a final
        # state (applied/errored/canceled). Re-pull a trailing day so recently created runs
        # pick up those transitions; runs that finalize later than that only refresh on a
        # full refresh.
        incremental_lookback=timedelta(hours=24),
    ),
    "state_versions": TerraformCloudEndpointConfig(
        name="state_versions",
        path="/state-versions",
        # The list endpoint takes workspace *name* + organization name filters (there is no
        # per-workspace-id path), so the fan-out fills both from the parent workspace row.
        params={
            "filter[organization][name]": "{organization}",
            "filter[workspace][name]": "{workspace_name}",
        },
        partition_key="created_at",
        incremental_fields=CREATED_AT_INCREMENTAL_FIELDS,
        sort_mode="desc",
        fan_out_over_workspaces=True,
        drop_fields=(
            "hosted_state_download_url",
            "hosted_json_state_download_url",
            "sanitized_state_download_url",
            "hosted_state_upload_url",
            "hosted_json_state_upload_url",
        ),
    ),
    "plans": TerraformCloudEndpointConfig(
        name="plans",
        path="/workspaces/{workspace_id}/runs",
        params={"include": "plan"},
        partition_key="run_created_at",
        incremental_fields=RUN_CREATED_AT_INCREMENTAL_FIELDS,
        sort_mode="desc",
        fan_out_over_workspaces=True,
        incremental_lookback=timedelta(hours=24),
        drop_fields=_LOG_URL_FIELDS,
        run_included_relationship="plan",
    ),
    "applies": TerraformCloudEndpointConfig(
        name="applies",
        path="/workspaces/{workspace_id}/runs",
        params={"include": "apply"},
        partition_key="run_created_at",
        incremental_fields=RUN_CREATED_AT_INCREMENTAL_FIELDS,
        sort_mode="desc",
        fan_out_over_workspaces=True,
        incremental_lookback=timedelta(hours=24),
        drop_fields=_LOG_URL_FIELDS,
        run_included_relationship="apply",
    ),
    "assessment_results": TerraformCloudEndpointConfig(
        name="assessment_results",
        # There is no list endpoint: only the workspace's current result is reachable. Merge
        # syncs keep earlier results, so the table builds a history over time.
        path="/assessment-results/{resource_id}",
        partition_key="created_at",
        incremental_fields=CREATED_AT_INCREMENTAL_FIELDS,
        sort_mode="desc",
        fan_out_over_workspaces=True,
        workspace_relationship="current-assessment-result",
        workspace_relationship_updated_at="last-assessment-result-at",
    ),
    "workspace_resources": TerraformCloudEndpointConfig(
        name="workspace_resources",
        path="/workspaces/{workspace_id}/resources",
        # Resource ids are only documented per workspace.
        primary_keys=["workspace_id", "id"],
        fan_out_over_workspaces=True,
    ),
}

ENDPOINTS = tuple(TERRAFORM_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TERRAFORM_CLOUD_ENDPOINTS.items()
}
