from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# Verified server-side against the live GraphQL API: `runs(filters:)` honors MongoDB-style
# `{"createdAt": {"$gt": ...}}` / `{"heartbeatAt": {"$gt": ...}}` filters (a future-dated
# cutoff returns zero rows). `heartbeatAt` advances while a run is active, so it also picks
# up state/summary changes on recently active runs that a `createdAt` cursor would miss.
_RUN_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "heartbeatAt",
        "type": IncrementalFieldType.DateTime,
        "field": "heartbeatAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Run-child tables (history, artifact lineage) have no timestamp of their own that the API
# filters on, so they inherit the parent run's `heartbeatAt`: an incremental sync re-reads only
# the runs that were active since the last sync, through the same verified `runs(filters:)`.
_RUN_CHILD_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "runHeartbeatAt",
        "type": IncrementalFieldType.DateTime,
        "field": "runHeartbeatAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=False)
class WeightsAndBiasesEndpointConfig:
    # GraphQL node ids are globally unique (they encode entity + project), so a single-column
    # key stays unique even though fan-out endpoints aggregate rows from every project.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # None for tables with no stable datetime column to partition on.
    partition_key: str | None = "createdAt"
    description: str | None = None


WANDB_ENDPOINTS: dict[str, WeightsAndBiasesEndpointConfig] = {
    "projects": WeightsAndBiasesEndpointConfig(),
    "runs": WeightsAndBiasesEndpointConfig(
        incremental_fields=_RUN_INCREMENTAL_FIELDS,
        description=(
            "One row per run across every project in the entity, including config, tags and "
            "summary metrics. Incremental syncs filter server-side on createdAt or heartbeatAt; "
            "pick heartbeatAt to also pick up state and metric changes on recently active runs"
        ),
    ),
    "sweeps": WeightsAndBiasesEndpointConfig(),
    "reports": WeightsAndBiasesEndpointConfig(),
    "artifacts": WeightsAndBiasesEndpointConfig(
        description=(
            "One row per artifact version across every project, walked per artifact type and "
            "collection. Projects with many run-history artifacts can make this table large"
        ),
    ),
    "artifact_types": WeightsAndBiasesEndpointConfig(
        description="One row per artifact type (model, dataset, ...) in each project",
    ),
    "artifact_collections": WeightsAndBiasesEndpointConfig(
        description="One row per artifact collection in each project, the named sequence each artifact version belongs to",
    ),
    "members": WeightsAndBiasesEndpointConfig(
        partition_key=None,
        description="Members of the entity. Join runs, sweeps and reports to it on the username",
    ),
    "run_artifacts": WeightsAndBiasesEndpointConfig(
        primary_keys=["runId", "direction", "artifactId"],
        incremental_fields=_RUN_CHILD_INCREMENTAL_FIELDS,
        partition_key="runCreatedAt",
        description=(
            "Run-to-artifact lineage: one row per artifact version a run used (input) or logged (output). "
            "Incremental syncs re-read the runs active since the last sync"
        ),
    ),
    "run_history": WeightsAndBiasesEndpointConfig(
        primary_keys=["runId", "step"],
        incremental_fields=_RUN_CHILD_INCREMENTAL_FIELDS,
        partition_key="runCreatedAt",
        description=(
            "The metrics each run logged, one row per step, with the logged values in a JSON metrics column. "
            "This table can be very large. Incremental syncs re-read the history of the runs active since the last sync"
        ),
    ),
    "entities": WeightsAndBiasesEndpointConfig(
        partition_key=None,
        description="The configured entity (user or team) itself, with its type, plan flags and storage use",
    ),
    "run_files": WeightsAndBiasesEndpointConfig(
        primary_keys=["runId", "name"],
        incremental_fields=_RUN_CHILD_INCREMENTAL_FIELDS,
        partition_key="runCreatedAt",
        description=(
            "One row per file a run uploaded, with its size and type. "
            "Incremental syncs re-read the files of the runs active since the last sync"
        ),
    ),
    "run_system_metrics": WeightsAndBiasesEndpointConfig(
        primary_keys=["runId", "timestamp"],
        incremental_fields=_RUN_CHILD_INCREMENTAL_FIELDS,
        partition_key="runCreatedAt",
        description=(
            "The CPU, GPU, memory, disk and network samples each run recorded, one row per sample, with the values "
            "in a JSON metrics column. W&B returns at most 5,000 evenly spaced samples per run. "
            "Incremental syncs re-read the samples of the runs active since the last sync"
        ),
    ),
}

ENDPOINTS = tuple(WANDB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WANDB_ENDPOINTS.items() if config.incremental_fields
}
