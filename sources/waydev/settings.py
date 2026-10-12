from products.warehouse_sources.backend.types import IncrementalField

ENDPOINTS = (
    "Metrics",
    "Incidents",
)

# Neither endpoint documents a server-side timestamp filter (Incidents only supports
# page/limit/repository_id, and Metrics is a static catalog), so both sync full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
