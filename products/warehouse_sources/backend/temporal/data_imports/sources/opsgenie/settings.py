from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class OpsgenieEndpointConfig:
    path: str  # Path under the API base URL, including the API version, e.g. "/v2/alerts"
    primary_key: str = "id"
    partition_key: Optional[str] = None  # Stable datetime field used to partition (never a mutable field)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True for endpoints that accept `limit`/`offset` pagination params. Endpoints left
    # False (teams, schedules, escalations, integrations) return their full collection in
    # a single response.
    paginated: bool = False
    # True only for the alert/incident search endpoints, which accept a `query` search
    # param with `createdAt >= <epoch millis>` filtering AND a `sort=createdAt&order=asc`
    # ordering we control. Both are required for safe incremental sync: the filter bounds
    # the window, the sort guarantees a stable ascending watermark. These endpoints also
    # hard-cap `offset + limit` at 20,000 per query, so backfills re-slice into new
    # createdAt windows when they hit the cap.
    supports_search_window: bool = False


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


OPSGENIE_ENDPOINTS: dict[str, OpsgenieEndpointConfig] = {
    "alerts": OpsgenieEndpointConfig(
        path="/v2/alerts",
        partition_key="createdAt",
        incremental_fields=_CREATED_AT_INCREMENTAL,
        paginated=True,
        # Incremental sync only picks up newly *created* alerts — Opsgenie's search syntax
        # can filter on createdAt but not updatedAt, so status changes to alerts created
        # before the cursor are not re-fetched. Run periodic full refreshes for
        # change capture.
        supports_search_window=True,
    ),
    "incidents": OpsgenieEndpointConfig(
        path="/v1/incidents",
        partition_key="createdAt",
        incremental_fields=_CREATED_AT_INCREMENTAL,
        paginated=True,
        supports_search_window=True,
    ),
    "users": OpsgenieEndpointConfig(
        path="/v2/users",
        paginated=True,
    ),
    "teams": OpsgenieEndpointConfig(
        path="/v2/teams",
    ),
    "schedules": OpsgenieEndpointConfig(
        path="/v2/schedules",
    ),
    "escalations": OpsgenieEndpointConfig(
        path="/v2/escalations",
    ),
    "services": OpsgenieEndpointConfig(
        path="/v1/services",
        paginated=True,
    ),
    "integrations": OpsgenieEndpointConfig(
        path="/v2/integrations",
    ),
}

ENDPOINTS = tuple(OPSGENIE_ENDPOINTS.keys())
