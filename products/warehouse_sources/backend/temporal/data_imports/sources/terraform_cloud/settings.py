from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
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
}

ENDPOINTS = tuple(TERRAFORM_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TERRAFORM_CLOUD_ENDPOINTS.items()
}
