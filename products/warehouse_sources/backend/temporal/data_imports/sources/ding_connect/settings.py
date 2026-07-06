from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

DingConnectMethod = Literal["GET", "POST"]


@dataclass
class DingConnectEndpointConfig:
    name: str
    path: str
    method: DingConnectMethod = "GET"
    # Key in the response envelope holding the row list. "" means the body itself is a single
    # object (GetBalance) which we wrap into a one-row list.
    data_selector: str = "Items"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-style datetime field to partition by; None for small static lookups.
    partition_key: Optional[str] = None
    # ListTransferRecords is the only unbounded endpoint and pages via Skip/Take in the POST body.
    # Reference endpoints return their whole (bounded) list in a single response.
    paginated: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


# DingConnect's REST API exposes reference/catalog lookups (Countries, Currencies, Providers,
# Products, Promotions, Balance) plus transaction history (TransferRecords). None of these expose
# a server-side timestamp filter — the catalog endpoints are static lookups and ListTransferRecords
# only accepts Skip/Take offset paging — so every table is full refresh. Transfer history is also
# only retained for ~2 months upstream, so each sync reflects the currently-retained window.
DING_CONNECT_ENDPOINTS: dict[str, DingConnectEndpointConfig] = {
    "Countries": DingConnectEndpointConfig(
        name="Countries",
        path="/api/V1/GetCountries",
        primary_keys=["CountryIso"],
    ),
    "Currencies": DingConnectEndpointConfig(
        name="Currencies",
        path="/api/V1/GetCurrencies",
        primary_keys=["CurrencyIso"],
    ),
    "Providers": DingConnectEndpointConfig(
        name="Providers",
        path="/api/V1/GetProviders",
        primary_keys=["ProviderCode"],
    ),
    "Products": DingConnectEndpointConfig(
        name="Products",
        path="/api/V1/GetProducts",
        primary_keys=["SkuCode"],
    ),
    # Promotions carry no unique identifier, so dedupe on the (provider, currency, start) tuple.
    "Promotions": DingConnectEndpointConfig(
        name="Promotions",
        path="/api/V1/GetPromotions",
        primary_keys=["ProviderCode", "CurrencyIso", "StartUtc"],
    ),
    # GetBalance returns a single object rather than an Items list; we wrap it into one row keyed
    # on the currency so a full-refresh replace keeps exactly one current-balance row per currency.
    "Balance": DingConnectEndpointConfig(
        name="Balance",
        path="/api/V1/GetBalance",
        data_selector="",
        primary_keys=["CurrencyIso"],
    ),
    "TransferRecords": DingConnectEndpointConfig(
        name="TransferRecords",
        path="/api/V1/ListTransferRecords",
        method="POST",
        paginated=True,
        primary_keys=["TransferRef"],
        partition_key="StartedUtc",
    ),
}

ENDPOINTS = tuple(DING_CONNECT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DING_CONNECT_ENDPOINTS.items()
}
