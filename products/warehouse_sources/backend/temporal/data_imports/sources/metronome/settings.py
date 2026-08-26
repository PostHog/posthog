from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

METRONOME_BASE_URL = "https://api.metronome.com"

# Every paginated Metronome list endpoint caps `limit` at 100.
PAGE_SIZE = 100

# List responses share a `{"data": [...], "next_page": "..."}` envelope, and the cursor goes back
# out under the name it arrived under.
DATA_SELECTOR = "data"
CURSOR_PATH = "next_page"
CURSOR_PARAM = "next_page"

# `GET /v1/auditLogs` is the only endpoint with a server-side lower bound on record time.
AUDIT_LOG_START_PARAM = "starting_on"


@dataclass(frozen=True)
class BodyFanoutConfig:
    """Fan-out whose parent id belongs in the child's JSON body.

    The declarative fan-out helper binds a resolved parent field into the child's *path* only, so
    a child like `POST /v2/contracts/list` — which takes `customer_id` in its body — walks the
    parent itself instead.
    """

    parent_name: str
    resolve_field: str
    body_param: str


# frozen=False: MetronomeEndpointConfig is passed as `endpoint_configs: Mapping[str, FanoutEndpointLike]`,
# and mypy treats a frozen dataclass's fields as read-only, which is incompatible with that
# Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class MetronomeEndpointConfig:
    name: str
    path: str
    primary_key: list[str]
    method: Literal["get", "post"] = "get"
    # Filter payload for the POST list endpoints. `limit` and `next_page` stay in the query string
    # on these; only the filters move into the body.
    json_body: dict[str, Any] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)
    # Endpoints whose response carries a `next_page` cursor; the rest return the whole collection.
    paginated: bool = True
    # Server-side lower bound for incremental syncs. Metronome rejects this window when a cursor
    # is also sent, so it only rides the first request of a run.
    incremental_start_param: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = PAGE_SIZE
    fanout: DependentEndpointConfig | None = None
    body_fanout: BodyFanoutConfig | None = None


# Customer-scoped children bind the parent's `id` into their path as `customer_id`. Every child
# row already carries its own `customer_id`, so nothing needs copying down from the parent.
_CUSTOMER_PATH_FANOUT = DependentEndpointConfig(
    parent_name="customers",
    resolve_param="customer_id",
    resolve_field="id",
    include_from_parent=[],
)


METRONOME_ENDPOINTS: dict[str, MetronomeEndpointConfig] = {
    "customers": MetronomeEndpointConfig(
        name="customers",
        path="/v1/customers",
        primary_key=["id"],
        partition_key="created_at",
        # No created/updated filter exists on this endpoint, so every run reads the whole list.
        # `only_archived` swaps the result set rather than widening it, so archived customers are
        # out of scope for this table.
    ),
    "invoices": MetronomeEndpointConfig(
        name="invoices",
        path="/v1/customers/{customer_id}/invoices",
        primary_key=["id"],
        # The endpoint's own docs give two different default orders, so pin one.
        extra_params={"sort": "date_asc"},
        # `line_items` is unbounded, so a full page of invoices can be very large. A smaller page
        # keeps each response, and the Arrow table built from it, within reach.
        page_size=25,
        fanout=_CUSTOMER_PATH_FANOUT,
    ),
    "contracts": MetronomeEndpointConfig(
        name="contracts",
        path="/v2/contracts/list",
        method="post",
        primary_key=["id"],
        partition_key="created_at",
        # Returns every contract for the customer in one response — no cursor, no `limit`.
        paginated=False,
        json_body={"include_archived": True},
        body_fanout=BodyFanoutConfig(parent_name="customers", resolve_field="id", body_param="customer_id"),
    ),
    "products": MetronomeEndpointConfig(
        name="products",
        path="/v1/contract-pricing/products/list",
        method="post",
        primary_key=["id"],
        # Archived products stay in the warehouse copy; the default filter hides them.
        json_body={"archive_filter": "ALL"},
    ),
    "rate_cards": MetronomeEndpointConfig(
        name="rate_cards",
        path="/v1/contract-pricing/rate-cards/list",
        method="post",
        primary_key=["id"],
        partition_key="created_at",
    ),
    "packages": MetronomeEndpointConfig(
        name="packages",
        path="/v1/packages/list",
        method="post",
        primary_key=["id"],
        partition_key="created_at",
        json_body={"archive_filter": "ALL"},
    ),
    "billable_metrics": MetronomeEndpointConfig(
        name="billable_metrics",
        path="/v1/billable-metrics",
        primary_key=["id"],
        extra_params={"include_archived": "true"},
    ),
    "pricing_units": MetronomeEndpointConfig(
        name="pricing_units",
        path="/v1/credit-types/list",
        primary_key=["id"],
    ),
    "audit_logs": MetronomeEndpointConfig(
        name="audit_logs",
        path="/v1/auditLogs",
        primary_key=["id"],
        # `date_asc` is the documented default, but pin it so the rows arrive in the order the
        # incremental watermark assumes.
        extra_params={"sort": "date_asc"},
        incremental_start_param=AUDIT_LOG_START_PARAM,
        incremental_fields=[incremental_field("timestamp")],
        default_incremental_field="timestamp",
        partition_key="timestamp",
    ),
}

ENDPOINTS = tuple(METRONOME_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in METRONOME_ENDPOINTS.items()
}
