from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class TempoEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Most list endpoints take limit/offset and return a `metadata.next` URL; holiday-schemes
    # returns the whole collection in one response.
    paginated: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side query param that filters rows updated on/after the watermark (e.g. `updatedFrom`).
    incremental_param: Optional[str] = None
    # Tempo's `orderBy` sorts by the given field DESCENDING; without it, worklogs default to
    # START_DATE_TIME ascending (per the official OpenAPI spec).
    order_by: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    partition_key: Optional[str] = None
    # The plans endpoint requires `from`/`to` query params; we send a wide fixed window.
    requires_date_window: bool = False


# Tempo REST API v4 list endpoints (https://apidocs.tempo.io). Only worklogs expose a documented
# server-side incremental filter (`updatedFrom`, matching rows created or updated on/after the
# given timestamp). `/plans` also documents `updatedFrom`, but its ordering is undocumented and we
# could not verify the filter against a live account, so it ships full refresh for now.
TEMPO_ENDPOINTS: dict[str, TempoEndpointConfig] = {
    "worklogs": TempoEndpointConfig(
        name="worklogs",
        path="/worklogs",
        # Worklog ids are numeric and unique across the whole Tempo instance.
        primary_keys=["tempoWorklogId"],
        incremental_fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "updatedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        incremental_param="updatedFrom",
        # `orderBy=UPDATED` returns worklogs newest-update-first, so the incremental watermark is
        # only committed once the sync completes (sort_mode="desc").
        order_by="UPDATED",
        sort_mode="desc",
        partition_key="createdAt",
    ),
    "accounts": TempoEndpointConfig(name="accounts", path="/accounts"),
    "customers": TempoEndpointConfig(name="customers", path="/customers"),
    "teams": TempoEndpointConfig(name="teams", path="/teams"),
    "plans": TempoEndpointConfig(name="plans", path="/plans", requires_date_window=True),
    "workload_schemes": TempoEndpointConfig(name="workload_schemes", path="/workload-schemes"),
    "holiday_schemes": TempoEndpointConfig(name="holiday_schemes", path="/holiday-schemes", paginated=False),
}

ENDPOINTS = tuple(TEMPO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TEMPO_ENDPOINTS.items()
}
