from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

API_BASE_URL = "https://api.alegra.com/api/{version}/"
PAGE_SIZE = 30
REQUEST_TIMEOUT = (10, 60)


@frozen
class AlegraEndpoint:
    path: str
    params: dict[str, str] = field(default_factory=dict)
    primary_keys: tuple[str, ...] = ("id",)
    partition_keys: tuple[str, ...] = ("id",)


ENDPOINTS: dict[str, AlegraEndpoint] = {
    "invoices": AlegraEndpoint(path="invoices", params={"order_field": "id", "order_direction": "ASC"}),
    "contacts": AlegraEndpoint(
        path="contacts", params={"order_field": "id", "order_direction": "ASC", "mode": "advanced"}
    ),
    "items": AlegraEndpoint(path="items", params={"order_field": "id", "order_direction": "ASC", "mode": "advanced"}),
    "incoming_payments": AlegraEndpoint(
        path="payments", params={"type": "in", "order_field": "id", "order_direction": "ASC"}
    ),
    "outgoing_payments": AlegraEndpoint(
        path="payments", params={"type": "out", "order_field": "id", "order_direction": "ASC"}
    ),
    "bills": AlegraEndpoint(path="bills", params={"order_field": "date", "order_direction": "ASC"}),
    "estimates": AlegraEndpoint(path="estimates", params={"order_field": "id", "order_direction": "ASC"}),
    "credit_notes": AlegraEndpoint(path="credit-notes"),
    "debit_notes": AlegraEndpoint(path="debit-notes"),
    # Alegra omits inactive bank accounts unless asked, but payments still reference them.
    "bank_accounts": AlegraEndpoint(
        path="bank-accounts", params={"order_field": "id", "order_direction": "ASC", "includeInactive": "true"}
    ),
    # Item categories only sort by the editable name, so keep the API default order.
    "item_categories": AlegraEndpoint(path="item-categories"),
    "warehouses": AlegraEndpoint(path="warehouses", params={"order_field": "id", "order_direction": "ASC"}),
    "inventory_adjustments": AlegraEndpoint(
        path="inventory-adjustments", params={"order_field": "id", "order_direction": "ASC"}
    ),
    # Warehouse transfers and taxes accept no sort parameters.
    "warehouse_transfers": AlegraEndpoint(path="warehouse-transfers"),
    "purchase_orders": AlegraEndpoint(path="purchase-orders", params={"order_field": "id", "order_direction": "ASC"}),
    # Recurring invoices only sort by editable schedule fields, so keep the API default order.
    "recurring_invoices": AlegraEndpoint(path="recurring-invoices"),
    "taxes": AlegraEndpoint(path="taxes"),
}

# Document dates can be edited, and server-side date filters have not been verified against a live account.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

# Alegra IDs can be UUIDs, and document dates are editable, so partition on the stable identifier.
PARTITION_MODE: Literal["md5"] = "md5"
PARTITION_COUNT = 16
