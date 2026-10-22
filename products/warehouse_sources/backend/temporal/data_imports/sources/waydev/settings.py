from products.warehouse_sources.backend.types import IncrementalField

ENDPOINTS = (
    "Metrics",
    "Incidents",
    "Repositories",
    "Contributors",
    "Teams",
)

# No endpoint documents a server-side timestamp filter (the list endpoints only take
# paging and name/state filters, and Metrics is a static catalog), so all sync full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
