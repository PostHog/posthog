from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

PAYPAL_HOSTS: dict[str, str] = {
    "live": "https://api-m.paypal.com",
    "sandbox": "https://api-m.sandbox.paypal.com",
}

# How each endpoint walks its result set:
#   date_window  -> Transaction Search: slice the range into windows, then page within each window
#   page_number  -> `page` / `page_size` with `total_pages` in the body
#   page_token   -> opaque `next_page_token` carried on the `rel="next"` HATEOAS link
#   single       -> one request, no pagination
PaginationMode = Literal["date_window", "page_number", "page_token", "single"]

# Transaction Search rejects a range wider than 31 days and caps a query at 10,000 records.
# A one-week slice keeps a busy merchant comfortably under the record cap.
TRANSACTION_WINDOW_DAYS = 7
# PayPal retains three years of searchable transaction history.
TRANSACTION_HISTORY_DAYS = 3 * 365
# Transactions can take up to three hours to become searchable, so an incremental run must
# re-read a trailing window instead of starting exactly at the previous watermark.
TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS = 24 * 60 * 60


@dataclass
class PayPalEndpointConfig:
    name: str
    path: str
    # Response key holding the row list.
    data_selector: str
    primary_key: list[str]
    pagination: PaginationMode
    page_size: int = 100
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None
    sort_mode: SortMode = "asc"


PAYPAL_ENDPOINTS: dict[str, PayPalEndpointConfig] = {
    "transactions": PayPalEndpointConfig(
        name="transactions",
        path="/v1/reporting/transactions",
        data_selector="transaction_details",
        # transaction_id is hoisted out of the nested `transaction_info` object, which is
        # where Transaction Search puts it — the row itself has no top-level id.
        primary_key=["transaction_id"],
        pagination="date_window",
        # Transaction Search allows up to 500 rows per page.
        page_size=500,
        incremental_fields=[incremental_field("transaction_initiation_date")],
        # Initiation date is stamped once; transaction_updated_date moves as the transaction settles.
        partition_key="transaction_initiation_date",
        # Windows are walked oldest-first, so the watermark only ever moves forward.
        sort_mode="asc",
    ),
    "balances": PayPalEndpointConfig(
        name="balances",
        path="/v1/reporting/balances",
        data_selector="balances",
        # One row per currency held by the account, as of the moment we asked.
        primary_key=["account_id", "currency"],
        pagination="single",
    ),
    "disputes": PayPalEndpointConfig(
        name="disputes",
        path="/v1/customer/disputes",
        data_selector="items",
        primary_key=["dispute_id"],
        pagination="page_token",
        # The disputes list caps page_size at 50.
        page_size=50,
        # `start_time` filters server-side on dispute creation time.
        incremental_fields=[incremental_field("create_time")],
        partition_key="create_time",
        # PayPal does not document the ordering of the disputes list, so the watermark is
        # committed only once a run finishes rather than after every batch.
        sort_mode="desc",
    ),
    "invoices": PayPalEndpointConfig(
        name="invoices",
        path="/v2/invoicing/invoices",
        data_selector="items",
        primary_key=["id"],
        pagination="page_number",
        # The invoice list has no updated-since filter (only the separate search endpoint
        # does), so it is full refresh.
    ),
    "plans": PayPalEndpointConfig(
        name="plans",
        path="/v1/billing/plans",
        data_selector="plans",
        primary_key=["id"],
        pagination="page_number",
        # Billing plan listings cap page_size at 20.
        page_size=20,
        partition_key="create_time",
    ),
    "products": PayPalEndpointConfig(
        name="products",
        path="/v1/catalogs/products",
        data_selector="products",
        primary_key=["id"],
        pagination="page_number",
        # Catalog product listings cap page_size at 20.
        page_size=20,
        partition_key="create_time",
    ),
}

ENDPOINTS = tuple(PAYPAL_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PAYPAL_ENDPOINTS.items() if config.incremental_fields
}
