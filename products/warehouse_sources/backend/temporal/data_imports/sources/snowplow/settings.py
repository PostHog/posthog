from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class SnowplowEndpointConfig:
    name: str
    path: str
    # Primary key columns for the merge upsert. Fan-out endpoints aggregate rows from every
    # parent (job run / pipeline), so their keys include the parent identifier to stay unique
    # table-wide — a bare step `name` or metric `window` would collide across parents.
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field to partition by (a run's start time / a metric bucket never changes).
    partition_key: Optional[str] = None
    # Key of the wrapping object holding the row list ({"pipelines": [...]}); None for bare arrays.
    data_key: Optional[str] = None
    # When True the endpoint is queried with a from/to time window sliced into bounded chunks
    # (the jobs API caps a window at 96 hours and only retains about the last week of runs).
    windowed: bool = False
    # When True the endpoint is called once per job run discovered in the time window.
    fan_out_over_runs: bool = False
    # When True the endpoint is called once per pipeline discovered via GET /pipelines/v1.
    fan_out_over_pipelines: bool = False
    # Whether the table is selected for sync by default in the schema picker.
    should_sync_default: bool = True


# Endpoint catalog. Snowplow's BDP Console API lives at console.snowplowanalytics.com/api/msc/v1
# and is authenticated with a short-lived JWT minted from an API key + key ID
# (GET /organizations/{orgId}/credentials/v3/token, then `Authorization: Bearer`).
#
# Only the time-windowed endpoints are synced incrementally: GET /jobs/v1/runs requires a from/to
# window (a genuine server-side filter), and the failed-events metrics endpoint accepts the same
# window params. Snowplow retains job runs for only about the preceding week and caps a query
# window at 96 hours with at most 10,000 rows, so incremental sync advances a rolling window
# rather than backfilling deep history. The remaining endpoints are small current-state catalogs
# with no server-side timestamp filter, so they ship as full refresh.
SNOWPLOW_ENDPOINTS: dict[str, SnowplowEndpointConfig] = {
    "pipelines": SnowplowEndpointConfig(
        name="pipelines",
        path="/pipelines/v1",
        primary_keys=["id"],
        data_key="pipelines",
    ),
    "users": SnowplowEndpointConfig(
        name="users",
        path="/users",
        primary_keys=["id"],
    ),
    "data_models": SnowplowEndpointConfig(
        name="data_models",
        path="/data-models/v1/models",
        # Data models have no id; GET /data-models/v1/models/{modelName} addresses them by name.
        primary_keys=["name"],
    ),
    "data_structures": SnowplowEndpointConfig(
        name="data_structures",
        path="/data-structures/v1",
        primary_keys=["hash"],
    ),
    "job_runs": SnowplowEndpointConfig(
        name="job_runs",
        path="/jobs/v1/runs",
        primary_keys=["runId"],
        partition_key="startTime",
        windowed=True,
        incremental_fields=[
            {
                "label": "startTime",
                "type": IncrementalFieldType.DateTime,
                "field": "startTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "job_run_steps": SnowplowEndpointConfig(
        name="job_run_steps",
        path="/jobs/v1/runs/{runId}/steps",
        # Step names are unique only within a run, so the injected runId keeps the key unique
        # table-wide across the fan-out.
        primary_keys=["runId", "name"],
        partition_key="runStartTime",
        windowed=True,
        fan_out_over_runs=True,
        incremental_fields=[
            {
                "label": "runStartTime",
                "type": IncrementalFieldType.DateTime,
                "field": "runStartTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "failed_event_metrics": SnowplowEndpointConfig(
        name="failed_event_metrics",
        path="/metrics/v1/pipelines/{pipelineId}/failed-events",
        # One row per (pipeline, failed-event error, time bucket).
        primary_keys=["pipelineId", "errorId", "window"],
        partition_key="window",
        fan_out_over_pipelines=True,
        incremental_fields=[
            {
                "label": "window",
                "type": IncrementalFieldType.DateTime,
                "field": "window",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(SNOWPLOW_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SNOWPLOW_ENDPOINTS.items()
}
