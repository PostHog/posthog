from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ORB_API_BASE_URL = "https://api.withorb.com/v1"

# Orb caps list endpoints at 100 items per page (default 20).
DEFAULT_PAGE_SIZE = 100


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=True)
class OrbEndpointConfig:
    name: str
    path: str
    table_name: str
    # Query-param key for the server-side "strictly greater than" timestamp filter used for
    # incremental syncs (e.g. "created_at[gt]"). None => the endpoint has no server-side time
    # filter, so it is full-refresh only.
    incremental_param: Optional[str] = None
    # Object field the incremental_param filters on (e.g. "created_at"). Drives INCREMENTAL_FIELDS.
    incremental_field: Optional[str] = None
    # Stable datetime field to partition by. Must never change after creation, so always a
    # creation-style field (created_at), never a mutable one.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = DEFAULT_PAGE_SIZE
    # False for endpoints that return their whole result in one response and take no `limit`.
    paginated: bool = True
    # Set for per-customer and per-subscription child endpoints, which fan out over the parent listing.
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return [_datetime_field(self.incremental_field)] if self.incremental_field else []

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_field


def _fanout(
    parent_name: str, resolve_param: str, child_params: Optional[dict[str, str]] = None
) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param=resolve_param,
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": resolve_param},
        # Set here as well as through page_size_param, because unpaginated children send no page size.
        parent_params={"limit": DEFAULT_PAGE_SIZE},
        child_params=child_params or {},
        # A parent deleted between the parent listing and its child fetch 404s; skip it rather
        # than failing the whole fan-out.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


def _customer_fanout(child_params: Optional[dict[str, str]] = None) -> DependentEndpointConfig:
    return _fanout("Customers", "customer_id", child_params)


def _subscription_fanout() -> DependentEndpointConfig:
    return _fanout("Subscriptions", "subscription_id")


# Orb list endpoints. All return `{"data": [...], "pagination_metadata": {...}}`, are
# cursor-paginated, and sort newest-first by creation time. Incremental endpoints expose a
# server-side `<field>[gt]` timestamp filter; the rest are full-refresh only. Endpoints with a
# `fanout` are per-customer or per-subscription and run once for every row of the parent listing.
#
# Invoices is the odd one out: it has no `created_at` filter, only `invoice_date[gt]`, so its
# incremental cursor is `invoice_date` while it still partitions on the stable `created_at`.
ORB_ENDPOINTS: dict[str, OrbEndpointConfig] = {
    "Customers": OrbEndpointConfig(
        name="Customers",
        path="/customers",
        table_name="customers",
        incremental_param="created_at[gt]",
        incremental_field="created_at",
        partition_key="created_at",
    ),
    "Plans": OrbEndpointConfig(
        name="Plans",
        path="/plans",
        table_name="plans",
        incremental_param="created_at[gt]",
        incremental_field="created_at",
        partition_key="created_at",
    ),
    "Subscriptions": OrbEndpointConfig(
        name="Subscriptions",
        path="/subscriptions",
        table_name="subscriptions",
        incremental_param="created_at[gt]",
        incremental_field="created_at",
        partition_key="created_at",
    ),
    "Invoices": OrbEndpointConfig(
        name="Invoices",
        path="/invoices",
        table_name="invoices",
        incremental_param="invoice_date[gt]",
        incremental_field="invoice_date",
        partition_key="created_at",
    ),
    "CreditNotes": OrbEndpointConfig(
        name="CreditNotes",
        path="/credit_notes",
        table_name="credit_notes",
        incremental_param="created_at[gt]",
        incremental_field="created_at",
        partition_key="created_at",
    ),
    "Items": OrbEndpointConfig(
        name="Items",
        path="/items",
        table_name="items",
        partition_key="created_at",
    ),
    "Coupons": OrbEndpointConfig(
        name="Coupons",
        path="/coupons",
        table_name="coupons",
    ),
    "Prices": OrbEndpointConfig(
        name="Prices",
        path="/prices",
        table_name="prices",
        partition_key="created_at",
    ),
    # Billable metric objects carry no created_at, so there is neither a cursor nor a stable
    # datetime to partition on.
    "BillableMetrics": OrbEndpointConfig(
        name="BillableMetrics",
        path="/metrics",
        table_name="billable_metrics",
    ),
    # Ledger entries are full refresh: decrements are grouped per day and pending entries can
    # later commit, so an entry can change after its created_at has passed the watermark.
    "CreditLedgerEntries": OrbEndpointConfig(
        name="CreditLedgerEntries",
        path="/customers/{customer_id}/credits/ledger",
        table_name="credit_ledger_entries",
        partition_key="created_at",
        primary_keys=["customer_id", "id"],
        fanout=_customer_fanout(),
    ),
    # The list filter is on `operation_time`, which the returned rows do not carry, so there is no
    # field to track a watermark on.
    "BalanceTransactions": OrbEndpointConfig(
        name="BalanceTransactions",
        path="/customers/{customer_id}/balance_transactions",
        table_name="balance_transactions",
        partition_key="created_at",
        primary_keys=["customer_id", "id"],
        fanout=_customer_fanout(),
    ),
    # Credit balances change as usage draws them down, so this is full refresh. Without
    # include_all_blocks Orb returns only unexpired, non-zero blocks. Like CreditLedgerEntries, this
    # reads Orb's default `credits` ledger: Orb has no endpoint that lists a customer's other ledger
    # currencies to fan out over.
    "CreditBlocks": OrbEndpointConfig(
        name="CreditBlocks",
        path="/customers/{customer_id}/credits",
        table_name="credit_blocks",
        primary_keys=["customer_id", "id"],
        fanout=_customer_fanout({"include_all_blocks": "true"}),
    ),
    # Costs are a cumulative day-by-day series over the current billing period (or the last active
    # one), returned in one unpaginated response. Each timeframe_end is one daily data point.
    "CustomerCosts": OrbEndpointConfig(
        name="CustomerCosts",
        path="/customers/{customer_id}/costs",
        table_name="customer_costs",
        partition_key="timeframe_start",
        primary_keys=["customer_id", "timeframe_start", "timeframe_end"],
        paginated=False,
        fanout=_customer_fanout(),
    ),
    "SubscriptionCosts": OrbEndpointConfig(
        name="SubscriptionCosts",
        path="/subscriptions/{subscription_id}/costs",
        table_name="subscription_costs",
        partition_key="timeframe_start",
        primary_keys=["subscription_id", "timeframe_start", "timeframe_end"],
        paginated=False,
        fanout=_subscription_fanout(),
    ),
    # Schedule entries carry no id. Full refresh, because a scheduled plan change sets the
    # end_date of the entry before it.
    "SubscriptionSchedules": OrbEndpointConfig(
        name="SubscriptionSchedules",
        path="/subscriptions/{subscription_id}/schedule",
        table_name="subscription_schedules",
        partition_key="created_at",
        primary_keys=["subscription_id", "start_date"],
        fanout=_subscription_fanout(),
    ),
}

ENDPOINTS = tuple(ORB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in ORB_ENDPOINTS.items() if cfg.incremental_fields
}
