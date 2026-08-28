from dataclasses import dataclass, field


@dataclass
class DatahubEndpointConfig:
    name: str
    # DataHub metadata-model entity name, interpolated into /openapi/v3/entity/{entity_type}.
    # Entity-name lookup is case-insensitive server-side; we use the registry's camelCase names.
    entity_type: str
    # Every DataHub entity is identified by its URN, unique across the whole metadata graph.
    primary_keys: list[str] = field(default_factory=lambda: ["urn"])


# DataHub OpenAPI v3 entity scroll endpoints. All full refresh only: the generic entity list has
# no server-side updated-since filter (freshness only exists as per-aspect
# systemMetadata.lastObserved, which mutates and isn't filterable here), so there is no timestamp
# cursor to advance an incremental sync. The scroll cursor makes a single full sweep resumable.
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
}

ENDPOINTS = tuple(DATAHUB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
