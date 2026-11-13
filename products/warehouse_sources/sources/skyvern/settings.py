from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class SkyvernEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # Some Skyvern list endpoints return a bare JSON array; others wrap the rows in an object
    # (e.g. /v1/schedules -> {"schedules": [...], "total_count": ...}). `data_key` names the wrapper
    # field when present, otherwise the response is treated as a bare array.
    data_key: Optional[str] = None
    # A STABLE creation timestamp used for datetime partitioning. Never a mutable field like
    # modified_at, whose partitions would rewrite on every sync.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Only true for endpoints exposing a genuine server-side timestamp filter (created_at_start).
    supports_incremental: bool = False
    default_incremental_field: Optional[str] = None
    # Safety overlap subtracted from the incremental watermark on every run. Skyvern run records
    # keep mutating (status, credits_used, finished_at) until they reach a terminal state, but the
    # only server-side filter is on the immutable created_at. Re-pulling a trailing window each run
    # lets merge pick up those late mutations for recently-created runs.
    incremental_lookback: Optional[timedelta] = None
    # Fan out over every workflow: enumerate workflows via /v1/agents, then pull each workflow's runs
    # from /v1/agents/{workflow_permanent_id}/runs (the only run endpoint with a created_at filter).
    fan_out_over_workflows: bool = False
    # Fan out over every run of every workflow (workflows -> runs -> this endpoint). The chain saves no
    # resume state, so a retried sync starts again from the first workflow.
    fan_out_over_runs: bool = False
    # Whether the fan-out child endpoint takes page/page_size. Unpaginated children return everything in
    # one response.
    child_paginated: bool = True
    # Copy the parent workflow's workflow_permanent_id onto each child row, for children whose rows do
    # not carry it.
    include_workflow_permanent_id: bool = False
    sort_mode: Optional[Literal["asc", "desc"]] = "desc"
    # Extra query params merged into every request for this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)


_CREATED_AT_FIELD: IncrementalField = {
    "label": "created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at",
    "field_type": IncrementalFieldType.DateTime,
}


SKYVERN_ENDPOINTS: dict[str, SkyvernEndpointConfig] = {
    # Workflow definitions (latest version per workflow_permanent_id). /v1/agents has no server-side
    # timestamp filter, so this is full refresh only.
    "workflows": SkyvernEndpointConfig(
        name="workflows",
        path="/v1/agents",
        extra_params={"only_workflows": "true"},
        primary_keys=["workflow_permanent_id"],
        partition_key="created_at",
        incremental_fields=[],
    ),
    # Task/workflow run history. Fanned out per workflow because /v1/agents/{workflow_id}/runs is the
    # only run endpoint that accepts created_at_start (the global /v1/runs caps page<=100, ~10k newest
    # runs, and has no time filter). Incremental on the immutable created_at with a lookback window.
    "runs": SkyvernEndpointConfig(
        name="runs",
        path="/v1/agents/{workflow_permanent_id}/runs",
        primary_keys=["workflow_run_id"],
        partition_key="created_at",
        supports_incremental=True,
        default_incremental_field="created_at",
        incremental_lookback=timedelta(days=3),
        fan_out_over_workflows=True,
        incremental_fields=[_CREATED_AT_FIELD],
    ),
    # Scheduled workflow runs. Wrapped response. No server-side time filter -> full refresh.
    "schedules": SkyvernEndpointConfig(
        name="schedules",
        path="/v1/schedules",
        data_key="schedules",
        primary_keys=["workflow_schedule_id"],
        partition_key="created_at",
        incremental_fields=[],
    ),
    # Persisted browser profiles (cookies/local storage snapshots). No server-side time filter.
    "browser_profiles": SkyvernEndpointConfig(
        name="browser_profiles",
        path="/v1/browser_profiles",
        primary_keys=["browser_profile_id"],
        partition_key="created_at",
        incremental_fields=[],
    ),
    # Stored credential metadata (secret values are never returned by the API, only metadata).
    # CredentialResponse carries no timestamp, so there is no partition key and no incremental option.
    "credentials": SkyvernEndpointConfig(
        name="credentials",
        path="/v1/credentials",
        primary_keys=["credential_id"],
        incremental_fields=[],
    ),
    "folders": SkyvernEndpointConfig(
        name="folders",
        path="/v1/folders",
        primary_keys=["folder_id"],
        partition_key="created_at",
        incremental_fields=[],
    ),
    # Current tag state per workflow. The response wraps the rows ({"workflow_permanent_id", "tags"}),
    # and a standalone label has a null key, so the key is workflow + key + value.
    "workflow_tags": SkyvernEndpointConfig(
        name="workflow_tags",
        path="/v1/agents/{workflow_permanent_id}/tags",
        data_key="tags",
        primary_keys=["workflow_permanent_id", "key", "value"],
        fan_out_over_workflows=True,
        child_paginated=False,
        include_workflow_permanent_id=True,
        incremental_fields=[],
    ),
    # Every saved version of every workflow. workflow_id identifies one version.
    "workflow_versions": SkyvernEndpointConfig(
        name="workflow_versions",
        path="/v1/agents/{workflow_permanent_id}/versions",
        primary_keys=["workflow_id"],
        partition_key="created_at",
        fan_out_over_workflows=True,
        child_paginated=False,
        incremental_fields=[],
    ),
    # Block and thought entries of each run, flattened from the nested timeline tree. One request per
    # run, so it is off by default. Incremental syncs bound the runs with created_at_start, like `runs`.
    "run_timeline": SkyvernEndpointConfig(
        name="run_timeline",
        path="/v1/runs/{workflow_run_id}/timeline",
        primary_keys=["workflow_run_id", "timeline_entry_id"],
        partition_key="created_at",
        should_sync_default=False,
        supports_incremental=True,
        default_incremental_field="created_at",
        incremental_lookback=timedelta(days=3),
        fan_out_over_runs=True,
        child_paginated=False,
        # Entries of different runs arrive in no global created_at order.
        sort_mode=None,
        incremental_fields=[_CREATED_AT_FIELD],
    ),
}

ENDPOINTS = tuple(SKYVERN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SKYVERN_ENDPOINTS.items()
}
