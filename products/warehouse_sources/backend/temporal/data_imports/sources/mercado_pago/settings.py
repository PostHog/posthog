from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Every Mercado Pago country site (.com.ar, .com.br, .com.mx, ...) is served by the same API host;
# only the docs are split per site.
MERCADO_PAGO_BASE_URL = "https://api.mercadopago.com"

# Requested page size for the search endpoints. Mercado Pago caps `limit` server-side, so a page can
# come back smaller than this; the paginator advances by the rows actually returned, which costs an
# extra page rather than truncating the sync.
PAGE_SIZE = 50


@dataclass
class MercadoPagoEndpointConfig:
    name: str
    path: str
    # jsonpath into the response body where the list of records lives. The `/search` endpoints wrap
    # rows in `results` alongside a `paging` block; merchant orders use `elements` + a flat `total`.
    data_selector: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # jsonpath to the grand total of matching rows. Used to stop paginating; when absent,
    # pagination stops on the first empty page.
    total_path: Optional[str] = None
    # jsonpath to the offset the server says it served this page from. Preferred over the locally
    # tracked offset so a server-side page-size cap can't desynchronise the walk.
    offset_path: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # A stable, never-changing datetime field to partition on. None disables partitioning.
    partition_key: Optional[str] = None
    # Whether the endpoint honors the server-side `range` + `begin_date`/`end_date` date window.
    # Only endpoints that genuinely filter server-side may advertise incremental fields.
    supports_date_range: bool = False
    # `sort` value used when there is no incremental cursor, so page boundaries stay stable while
    # rows are being created during a sync.
    default_sort_field: Optional[str] = None
    extra_params: dict[str, str] = field(default_factory=dict)


# Only the directly queryable search endpoints are exposed. Settlement/release reports use a
# separate async config -> generate -> download file flow, which is a different transport entirely
# and is deliberately out of scope here.
MERCADO_PAGO_ENDPOINTS: dict[str, MercadoPagoEndpointConfig] = {
    # `/v1/payments/search` is the only endpoint documented to accept the `range` +
    # `begin_date`/`end_date` window, so it is the only incremental table. Note Mercado Pago caps
    # the searchable window at the last 12 months, so a first sync cannot backfill further back.
    "payments": MercadoPagoEndpointConfig(
        name="payments",
        path="/v1/payments/search",
        data_selector="results",
        total_path="paging.total",
        offset_path="paging.offset",
        incremental_fields=[incremental_field("date_last_updated"), incremental_field("date_created")],
        partition_key="date_created",
        supports_date_range=True,
        default_sort_field="date_created",
    ),
    "merchant_orders": MercadoPagoEndpointConfig(
        name="merchant_orders",
        path="/merchant_orders/search",
        data_selector="elements",
        total_path="total",
        partition_key="date_created",
    ),
    "subscriptions": MercadoPagoEndpointConfig(
        name="subscriptions",
        path="/preapproval/search",
        data_selector="results",
        total_path="paging.total",
        offset_path="paging.offset",
        partition_key="date_created",
    ),
    "subscription_plans": MercadoPagoEndpointConfig(
        name="subscription_plans",
        path="/preapproval_plan/search",
        data_selector="results",
        total_path="paging.total",
        offset_path="paging.offset",
        partition_key="date_created",
    ),
    "authorized_payments": MercadoPagoEndpointConfig(
        name="authorized_payments",
        path="/authorized_payments/search",
        data_selector="results",
        total_path="paging.total",
        offset_path="paging.offset",
        partition_key="date_created",
    ),
}

ENDPOINTS = tuple(MERCADO_PAGO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields
    for name, endpoint in MERCADO_PAGO_ENDPOINTS.items()
    if endpoint.incremental_fields
}
