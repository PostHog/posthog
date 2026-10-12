from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

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


@dataclass
class WeightsAndBiasesEndpointConfig:
    # GraphQL node ids are globally unique (they encode entity + project), so a single-column
    # key stays unique even though fan-out endpoints aggregate rows from every project.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str = "createdAt"
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
}

ENDPOINTS = tuple(WANDB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WANDB_ENDPOINTS.items() if config.incremental_fields
}
