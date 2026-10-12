from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Airwallex splits its list endpoints across two pagination conventions.
# "page_num": zero-based page numbers plus `has_more` in the body.
# "cursor": an opaque token returned as `page_after` and sent back as `page`.
PaginationStyle = Literal["page_num", "cursor"]


@frozen
class AirwallexEndpointConfig:
    name: str
    path: str
    pagination: PaginationStyle
    # Query param carrying the incremental lower bound. Airwallex names it differently per
    # endpoint: `from_created_at` on most, `from_settled_at` on settlements, `from_date` on
    # beneficiaries.
    start_param: str = "from_created_at"
    # Response field the `start_param` filters on, used as the incremental cursor.
    cursor_field: str = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = "created_at"
    page_size: int = 500
    # Fields stripped from every row before it lands in the warehouse (e.g. a live client secret).
    drop_fields: tuple[str, ...] = ()


def _incremental_field(name: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


AIRWALLEX_ENDPOINTS: dict[str, AirwallexEndpointConfig] = {
    # The account ledger: every movement that changed an Airwallex balance.
    "FinancialTransactions": AirwallexEndpointConfig(
        name="FinancialTransactions",
        path="/api/v1/financial_transactions",
        pagination="page_num",
    ),
    "Deposits": AirwallexEndpointConfig(
        name="Deposits",
        path="/api/v1/deposits",
        pagination="page_num",
    ),
    "PaymentIntents": AirwallexEndpointConfig(
        name="PaymentIntents",
        path="/api/v1/pa/payment_intents",
        pagination="page_num",
        # `client_secret` authorizes a browser/app to complete the payment; a still-valid one must
        # never land in the warehouse.
        drop_fields=("client_secret",),
    ),
    "PaymentAttempts": AirwallexEndpointConfig(
        name="PaymentAttempts",
        path="/api/v1/pa/payment_attempts",
        pagination="page_num",
    ),
    "Refunds": AirwallexEndpointConfig(
        name="Refunds",
        path="/api/v1/pa/refunds",
        pagination="page_num",
    ),
    "Customers": AirwallexEndpointConfig(
        name="Customers",
        path="/api/v1/pa/customers",
        pagination="page_num",
        # `client_secret` authorizes a browser/app to act as this customer; a still-valid one must
        # never land in the warehouse.
        drop_fields=("client_secret",),
    ),
    # Settlements are the one endpoint keyed on something other than `id`, and the only one whose
    # time filter bounds `settled_at` rather than `created_at`. Partitioning stays on `created_at`,
    # which never moves, while `settled_at` fills in when a pending settlement completes.
    "Settlements": AirwallexEndpointConfig(
        name="Settlements",
        path="/api/v1/pa/financial/settlements",
        pagination="page_num",
        start_param="from_settled_at",
        cursor_field="settled_at",
        primary_keys=["settlement_id"],
    ),
    # Payout recipients. The filter is named `from_date` but the docs state it bounds `created_at`.
    "Beneficiaries": AirwallexEndpointConfig(
        name="Beneficiaries",
        path="/api/v1/beneficiaries",
        pagination="page_num",
        start_param="from_date",
    ),
    "Transfers": AirwallexEndpointConfig(
        name="Transfers",
        path="/api/v1/transfers",
        pagination="cursor",
    ),
    "GlobalAccounts": AirwallexEndpointConfig(
        name="GlobalAccounts",
        path="/api/v1/global_accounts",
        pagination="cursor",
    ),
    "Invoices": AirwallexEndpointConfig(
        name="Invoices",
        path="/api/v1/billing/invoices",
        pagination="cursor",
    ),
    "Subscriptions": AirwallexEndpointConfig(
        name="Subscriptions",
        path="/api/v1/billing/subscriptions",
        pagination="cursor",
    ),
    "BillingCustomers": AirwallexEndpointConfig(
        name="BillingCustomers",
        path="/api/v1/billing/billing_customers",
        pagination="cursor",
    ),
}

ENDPOINTS = tuple(AIRWALLEX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: _incremental_field(config.cursor_field) for name, config in AIRWALLEX_ENDPOINTS.items()
}
