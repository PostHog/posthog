from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BOL_BASE_URL = "https://api.bol.com/retailer"
BOL_TOKEN_URL = "https://login.bol.com/token"

# Each bol resource versions on its own. Offers moved to v11; the other resources are still on v10.
ACCEPT_V10 = "application/vnd.retailer.v10+json"
ACCEPT_V11 = "application/vnd.retailer.v11+json"

OFFERS_PAGE_SIZE = 100

# The invoice list takes a period of at most 31 days, and invoice details reach 2 years back.
INVOICE_WINDOW_DAYS = 31
INVOICE_HISTORY_DAYS = 2 * 365

Pagination = Literal["pages", "cursor", "invoice_windows"]


@frozen
class BolEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...]
    pagination: Pagination = "pages"
    accept: str = ACCEPT_V10
    # One pass per parameter set, for list endpoints that only return one fulfilment method or one
    # handled state per call.
    passes: tuple[tuple[tuple[str, str], ...], ...] = ((),)
    incremental_fields: tuple[IncrementalField, ...] = ()
    partition_key: str | None = None


BOL_ENDPOINTS: dict[str, BolEndpointConfig] = {
    "orders": BolEndpointConfig(
        name="orders",
        path="/orders",
        data_selector="orders",
        primary_keys=("orderId",),
        # The list defaults to open orders shipped by the retailer only.
        passes=((("status", "ALL"), ("fulfilment-method", "ALL")),),
        partition_key="orderPlacedDateTime",
    ),
    "shipments": BolEndpointConfig(
        name="shipments",
        path="/shipments",
        data_selector="shipments",
        primary_keys=("shipmentId",),
        passes=((("fulfilment-method", "FBR"),), (("fulfilment-method", "FBB"),)),
        partition_key="shipmentDateTime",
    ),
    "returns": BolEndpointConfig(
        name="returns",
        path="/returns",
        data_selector="returns",
        primary_keys=("returnId",),
        passes=tuple(
            (("handled", handled), ("fulfilment-method", method))
            for method in ("FBR", "FBB")
            for handled in ("false", "true")
        ),
        partition_key="registrationDateTime",
    ),
    "inventory": BolEndpointConfig(
        name="inventory",
        path="/inventory",
        data_selector="inventory",
        primary_keys=("ean",),
    ),
    "invoices": BolEndpointConfig(
        name="invoices",
        path="/invoices",
        data_selector="invoiceListItems",
        primary_keys=("invoiceId",),
        pagination="invoice_windows",
    ),
    "offers": BolEndpointConfig(
        name="offers",
        path="/offers",
        data_selector="offers",
        primary_keys=("offerId",),
        pagination="cursor",
        accept=ACCEPT_V11,
        incremental_fields=(
            {
                "label": "lastModifiedDateTime",
                "type": IncrementalFieldType.DateTime,
                "field": "lastModifiedDateTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ),
    ),
}

ENDPOINTS = tuple(BOL_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in BOL_ENDPOINTS.items()
}
