from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
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
}

ENDPOINTS = tuple(SKYVERN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SKYVERN_ENDPOINTS.items()
}
