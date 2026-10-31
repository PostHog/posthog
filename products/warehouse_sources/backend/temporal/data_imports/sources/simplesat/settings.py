from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class SimplesatEndpointConfig:
    name: str
    path: str
    # Simplesat list responses wrap records under a key named after the resource
    # (e.g. {"surveys": [...], "next": ...}), so the extraction key is per-endpoint.
    list_key: str
    # A few list endpoints are exposed only as POST `/<resource>/search` collection endpoints.
    method: str = "GET"
    # Simplesat object IDs are unique per account, so `id` is a safe primary key everywhere.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Most list endpoints cap a page at 100 records; the largest page minimises round trips.
    page_size: int = 100
    # Maps an incremental field to the query param that filters on it server-side.
    incremental_param_by_field: dict[str, str] = field(default_factory=dict)
    partition_key: str | None = None


# Simplesat v1 top-level list endpoints. Only `customers` syncs incrementally, through its
# documented `created_after` / `modified_after` filters. `answers` and `responses` accept optional
# start_date/end_date filters, but the API's ordering guarantees for those filters aren't documented
# well enough to advance an incremental cursor safely, so they stay full refresh (see the
# implementing-warehouse-sources skill).
SIMPLESAT_ENDPOINTS: dict[str, SimplesatEndpointConfig] = {
    "surveys": SimplesatEndpointConfig(name="surveys", path="/surveys", list_key="surveys", method="GET"),
    "questions": SimplesatEndpointConfig(name="questions", path="/questions", list_key="questions", method="GET"),
    "answers": SimplesatEndpointConfig(name="answers", path="/answers/search", list_key="answers", method="POST"),
    "responses": SimplesatEndpointConfig(
        name="responses", path="/responses/search", list_key="responses", method="POST"
    ),
    "customers": SimplesatEndpointConfig(
        name="customers",
        path="/customers",
        list_key="customers",
        method="GET",
        page_size=250,
        incremental_param_by_field={"modified": "modified_after", "created": "created_after"},
        partition_key="created",
    ),
}

ENDPOINTS = tuple(SIMPLESAT_ENDPOINTS.keys())


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [_datetime_field(f) for f in config.incremental_param_by_field]
    for name, config in SIMPLESAT_ENDPOINTS.items()
    if config.incremental_param_by_field
}
