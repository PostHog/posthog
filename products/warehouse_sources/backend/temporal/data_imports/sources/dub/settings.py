from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    SortMode,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

DUB_BASE_URL = "https://api.dub.co"


@dataclass
class DubEndpointConfig:
    name: str
    path: str
    # "cursor" = startingAfter cursor pagination; "page" = 1-based page-number pagination.
    pagination: Literal["cursor", "page"]
    page_size: int = 100
    page_size_param: str = "pageSize"
    primary_key: str = "id"
    partition_key: Optional[str] = "createdAt"
    partition_format: PartitionFormat = "month"
    sort_mode: SortMode = "desc"
    params: dict[str, str] = field(default_factory=dict)
    # Set for the /events streams; selects which event type the shared endpoint returns.
    event_type: Optional[str] = None


def _event_endpoint(name: str, event_type: str, primary_key: str) -> DubEndpointConfig:
    return DubEndpointConfig(
        name=name,
        path="/events",
        pagination="page",
        # /events allows up to 1000 rows per page; larger pages keep us well inside
        # Dub's stricter per-second analytics rate limits.
        page_size=500,
        page_size_param="limit",
        primary_key=primary_key,
        partition_key="timestamp",
        partition_format="week",
        sort_mode="asc",
        params={"event": event_type, "sortBy": "timestamp", "sortOrder": "asc"},
        event_type=event_type,
    )


DUB_ENDPOINTS: dict[str, DubEndpointConfig] = {
    "links": DubEndpointConfig(name="links", path="/links", pagination="cursor"),
    "click_events": _event_endpoint("click_events", "clicks", primary_key="click_id"),
    "lead_events": _event_endpoint("lead_events", "leads", primary_key="eventId"),
    "sale_events": _event_endpoint("sale_events", "sales", primary_key="eventId"),
    "customers": DubEndpointConfig(name="customers", path="/customers", pagination="cursor"),
    "tags": DubEndpointConfig(
        name="tags",
        path="/tags",
        pagination="page",
        partition_key=None,
        # Explicit stable sort so rows don't shift across page boundaries mid-sync.
        params={"sortBy": "createdAt", "sortOrder": "asc"},
        sort_mode="asc",
    ),
    "domains": DubEndpointConfig(name="domains", path="/domains", pagination="page", page_size=50),
    "folders": DubEndpointConfig(name="folders", path="/folders", pagination="page", page_size=50),
    "partners": DubEndpointConfig(
        name="partners",
        path="/partners",
        pagination="page",
        params={"sortBy": "createdAt", "sortOrder": "asc"},
        sort_mode="asc",
    ),
    "commissions": DubEndpointConfig(name="commissions", path="/commissions", pagination="cursor"),
    "payouts": DubEndpointConfig(name="payouts", path="/payouts", pagination="page"),
}

ENDPOINTS = tuple(DUB_ENDPOINTS.keys())

# Only the /events streams expose a genuine server-side timestamp filter (start/end) with a
# stable ascending sort, so they're the only incremental candidates. Commissions document a
# start/end filter too, but it keys on createdAt while commission status keeps mutating after
# creation (pending -> processed -> paid), so an incremental sync would freeze stale statuses —
# those stay full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "click_events": [incremental_field("timestamp")],
    "lead_events": [incremental_field("timestamp")],
    "sale_events": [incremental_field("timestamp")],
}

# Endpoints gated by Dub plan or product setup: /events needs a Business plan or higher,
# /payouts needs a Business partner-program plan, and /partners + /commissions require a
# partner program. Used by get_endpoint_permissions to surface per-table reachability.
PLAN_GATED_ENDPOINTS = ("click_events", "lead_events", "sale_events", "partners", "commissions", "payouts")
