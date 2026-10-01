from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class SimEndpoint:
    path: str
    primary_key: str
    partition_key: str
    sort_field: str


ENDPOINTS: dict[str, SimEndpoint] = {
    "workflows": SimEndpoint(path="workflows", primary_key="id", partition_key="createdAt", sort_field="createdAt"),
    "logs": SimEndpoint(path="logs", primary_key="runId", partition_key="startedAt", sort_field="startedAt"),
}

# Run status and cost can change after startedAt, and workflows have no timestamp filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

PAGE_SIZE = 100
