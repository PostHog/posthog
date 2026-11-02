from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Synthesized surrogate key for a timeseries row. DataHub's own uniqueness rule for a timeseries
# document spans the timestamp, event granularity, urn, message id and partition spec, and none of
# those is unique on its own, so the source hashes them into this column.
TIMESERIES_ROW_ID_COLUMN = "id"

# Every timeseries aspect carries this epoch-millis field, and the scroll endpoint filters on it
# server-side, so it is the cursor for an incremental sync.
TIMESERIES_INCREMENTAL_FIELD = "timestampMillis"


@frozen
class DatahubEndpointConfig:
    name: str
    # DataHub metadata-model entity name, interpolated into /openapi/v3/entity/{entity_type}.
    # Entity-name lookup is case-insensitive server-side; we use the registry's camelCase names.
    entity_type: str
    # Every DataHub entity is identified by its URN, unique across the whole metadata graph.
    primary_keys: list[str] = field(default_factory=lambda: ["urn"])
    # Timeseries aspect of `entity_type` to scroll instead of the entity's versioned aspects. When
    # set, the endpoint reads /openapi/v2/timeseries/{entity_type}/{timeseries_aspect} and yields
    # one row per recorded event rather than one row per entity.
    timeseries_aspect: Optional[str] = None


def _timeseries_endpoint(name: str, entity_type: str, aspect: str) -> DatahubEndpointConfig:
    return DatahubEndpointConfig(
        name=name,
        entity_type=entity_type,
        primary_keys=[TIMESERIES_ROW_ID_COLUMN],
        timeseries_aspect=aspect,
    )


# DataHub OpenAPI v3 entity scroll endpoints and OpenAPI v2 timeseries aspect scroll endpoints.
#
# Entity endpoints are full refresh only: the generic entity list has no server-side updated-since
# filter (freshness only exists as per-aspect systemMetadata.lastObserved, which mutates and isn't
# filterable here), so there is no timestamp cursor to advance an incremental sync. The scroll
# cursor makes a single full sweep resumable.
#
# Lineage edges ride along on the entities themselves (datasets carry the upstreamLineage aspect,
# data jobs carry dataJobInputOutput), so no separate per-entity relationship fan-out is needed.
DATAHUB_ENDPOINTS: dict[str, DatahubEndpointConfig] = {
    "datasets": DatahubEndpointConfig(name="datasets", entity_type="dataset"),
    "containers": DatahubEndpointConfig(name="containers", entity_type="container"),
    "dashboards": DatahubEndpointConfig(name="dashboards", entity_type="dashboard"),
    "charts": DatahubEndpointConfig(name="charts", entity_type="chart"),
    "data_flows": DatahubEndpointConfig(name="data_flows", entity_type="dataFlow"),
    "data_jobs": DatahubEndpointConfig(name="data_jobs", entity_type="dataJob"),
    "data_platforms": DatahubEndpointConfig(name="data_platforms", entity_type="dataPlatform"),
    "data_products": DatahubEndpointConfig(name="data_products", entity_type="dataProduct"),
    "domains": DatahubEndpointConfig(name="domains", entity_type="domain"),
    "glossary_terms": DatahubEndpointConfig(name="glossary_terms", entity_type="glossaryTerm"),
    "glossary_nodes": DatahubEndpointConfig(name="glossary_nodes", entity_type="glossaryNode"),
    "tags": DatahubEndpointConfig(name="tags", entity_type="tag"),
    "users": DatahubEndpointConfig(name="users", entity_type="corpuser"),
    "groups": DatahubEndpointConfig(name="groups", entity_type="corpGroup"),
    "data_process_instances": DatahubEndpointConfig(name="data_process_instances", entity_type="dataProcessInstance"),
    "assertions": DatahubEndpointConfig(name="assertions", entity_type="assertion"),
    # Only fields that have been materialized as their own entity appear here. The full column list
    # of a dataset stays in its schemaMetadata aspect on the `datasets` table.
    "schema_fields": DatahubEndpointConfig(name="schema_fields", entity_type="schemaField"),
    "data_process_instance_run_events": _timeseries_endpoint(
        "data_process_instance_run_events", "dataProcessInstance", "dataProcessInstanceRunEvent"
    ),
    "assertion_run_events": _timeseries_endpoint("assertion_run_events", "assertion", "assertionRunEvent"),
    "dataset_profiles": _timeseries_endpoint("dataset_profiles", "dataset", "datasetProfile"),
    "dataset_usage_statistics": _timeseries_endpoint("dataset_usage_statistics", "dataset", "datasetUsageStatistics"),
    "dataset_operations": _timeseries_endpoint("dataset_operations", "dataset", "operation"),
}

ENDPOINTS = tuple(DATAHUB_ENDPOINTS.keys())

TIMESERIES_ENDPOINTS = tuple(name for name, config in DATAHUB_ENDPOINTS.items() if config.timeseries_aspect)

# Merge only: the server-side `startTimeMillis` bound is inclusive, so every sync re-reads the
# boundary event and an append would land it a second time.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": TIMESERIES_INCREMENTAL_FIELD,
            "type": IncrementalFieldType.Integer,
            "field": TIMESERIES_INCREMENTAL_FIELD,
            "field_type": IncrementalFieldType.Integer,
        }
    ]
    for name in TIMESERIES_ENDPOINTS
}
