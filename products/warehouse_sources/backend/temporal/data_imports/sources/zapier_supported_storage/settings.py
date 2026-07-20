from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class ZapierSupportedStorageEndpointConfig:
    name: str
    primary_keys: list[str]
    should_sync_default: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Storage by Zapier exposes a single endpoint (`GET /api/records`) that returns the whole store
# as one flat `{key: value}` JSON object. We materialize it as one row per key. The store carries
# no created/updated timestamps and there is no list/pagination beyond fetching everything, so the
# only sync mode possible is full refresh. `key` is unique within a store (a store is identified by
# its secret, which is fixed per source connection), so it is a safe table-wide primary key.
ZAPIER_SUPPORTED_STORAGE_ENDPOINTS: dict[str, ZapierSupportedStorageEndpointConfig] = {
    "records": ZapierSupportedStorageEndpointConfig(
        name="records",
        primary_keys=["key"],
    ),
}

ENDPOINTS = tuple(ZAPIER_SUPPORTED_STORAGE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ZAPIER_SUPPORTED_STORAGE_ENDPOINTS.items()
}
