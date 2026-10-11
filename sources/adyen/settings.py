from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Adyen splits its read APIs across three hosts with independent versions, so each endpoint
# names the API it belongs to rather than sharing one base URL.
AdyenApi = Literal["transfers", "configuration", "management", "reports"]

# `cursor` — Transfers API `_links.next` with an opaque `cursor` query param.
# `offset` — Configuration API `offset`/`limit`.
# `page` — Management API `pageNumber`/`pageSize`.
# `fanout_offset` — offset pagination per parent id resolved from another endpoint.
# `report_batch` — no pagination: walk sequential report batch numbers, one CSV file each.
AdyenPagination = Literal["cursor", "offset", "page", "fanout_offset", "report_batch"]


@dataclass(frozen=True)
class AdyenEndpointConfig:
    name: str
    api: AdyenApi
    path: str
    primary_key: tuple[str, ...]
    pagination: AdyenPagination
    # Key the rows live under in the JSON body (unused for report endpoints).
    data_key: str | None = None
    # Transfers endpoints reject requests without a createdSince/createdUntil window.
    window_filtered: bool = False
    partition_key: str | None = None
    requires_balance_platform: bool = False
    requires_merchant_account: bool = False
    # Fan-out children: the endpoint whose row ids fill the `{parent_id}` placeholder.
    parent: str | None = None
    description: str = ""


ADYEN_ENDPOINTS: dict[str, AdyenEndpointConfig] = {
    "AccountHolders": AdyenEndpointConfig(
        name="AccountHolders",
        api="configuration",
        path="/balancePlatforms/{balance_platform}/accountHolders",
        primary_key=("id",),
        pagination="offset",
        data_key="accountHolders",
        requires_balance_platform=True,
        description="Account holders in your balance platform, each representing a legal entity you onboarded.",
    ),
    "BalanceAccounts": AdyenEndpointConfig(
        name="BalanceAccounts",
        api="configuration",
        path="/accountHolders/{parent_id}/balanceAccounts",
        primary_key=("id",),
        pagination="fanout_offset",
        data_key="balanceAccounts",
        parent="AccountHolders",
        requires_balance_platform=True,
        description="Balance accounts holding funds for each account holder in your balance platform.",
    ),
    "Companies": AdyenEndpointConfig(
        name="Companies",
        api="management",
        path="/companies",
        primary_key=("id",),
        pagination="page",
        data_key="data",
        description="Company accounts your API credential can access.",
    ),
    "MerchantAccounts": AdyenEndpointConfig(
        name="MerchantAccounts",
        api="management",
        path="/merchants",
        primary_key=("id",),
        pagination="page",
        data_key="data",
        description="Merchant accounts your API credential can access, with their processing configuration.",
    ),
    "SettlementDetailReports": AdyenEndpointConfig(
        name="SettlementDetailReports",
        api="reports",
        path="settlement_detail_report_batch_{batch_number}.csv",
        primary_key=("batch_number", "psp_reference", "type", "modification_reference"),
        pagination="report_batch",
        requires_merchant_account=True,
        description="Transaction-level settlement lines from the settlement details report, one row per settled payment or fee.",
    ),
    "Transactions": AdyenEndpointConfig(
        name="Transactions",
        api="transfers",
        path="/transactions",
        primary_key=("id",),
        pagination="cursor",
        data_key="data",
        window_filtered=True,
        partition_key="creationDate",
        requires_balance_platform=True,
        description="Individual movements of funds booked against a balance account.",
    ),
    "Transfers": AdyenEndpointConfig(
        name="Transfers",
        api="transfers",
        path="/transfers",
        primary_key=("id",),
        pagination="cursor",
        data_key="data",
        window_filtered=True,
        partition_key="createdAt",
        requires_balance_platform=True,
        description="Transfer instructions such as payouts, top-ups and internal transfers.",
    ),
}

ENDPOINTS = tuple(ADYEN_ENDPOINTS.keys())

# Only endpoints with a real server-side filter are incremental: the Transfers API filters on
# `createdSince`/`createdUntil`, and settlement reports are addressed by an ascending batch
# number. The Configuration and Management endpoints expose no updated-since filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Transactions": [incremental_field("creationDate")],
    "Transfers": [incremental_field("createdAt")],
    "SettlementDetailReports": [incremental_field("batch_number", IncrementalFieldType.Integer)],
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {name: config.description for name, config in ADYEN_ENDPOINTS.items()}
