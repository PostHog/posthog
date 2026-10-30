from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)


@dataclass(frozen=True)
class PaystackEndpointConfig:
    # API path relative to https://api.paystack.co (e.g. "/transaction").
    path: str
    # Paystack list resources expose a globally-unique integer `id`, unique across the account.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Most list endpoints take `perPage`; a few newer ones document `per_page` instead.
    page_size_param: str = "perPage"
    # Paged by an opaque `meta.next` cursor instead of `page` / `perPage`.
    cursor_paginated: bool = False
    # Set for resources only listed per parent row; the parent is re-listed each sync.
    fanout: Optional[DependentEndpointConfig] = None


# Paystack list endpoints. Each returns a `{"status", "message", "data": [...], "meta": {...}}`
# envelope and paginates by `page` / `perPage` (default 50, max 100). The schema name (dict key)
# is what `get_schemas` reports and what the synced warehouse table is named after.
#
# All endpoints are full-refresh today. Paystack list endpoints return rows newest-first
# (descending by creation time) and expose no documented stable ascending sort parameter, and the
# `from` / `to` creation-time filters could not be verified against the live API (no test
# credentials). Declaring incremental on unverified ordering risks watermark corruption, so
# incremental sync is intentionally deferred — see the note in `paystack.py`.
PAYSTACK_ENDPOINTS: dict[str, PaystackEndpointConfig] = {
    "Transactions": PaystackEndpointConfig(path="/transaction"),
    "Customers": PaystackEndpointConfig(path="/customer"),
    "Subscriptions": PaystackEndpointConfig(path="/subscription"),
    "Plans": PaystackEndpointConfig(path="/plan"),
    "Products": PaystackEndpointConfig(path="/product"),
    "PaymentRequests": PaystackEndpointConfig(path="/paymentrequest"),
    "Settlements": PaystackEndpointConfig(path="/settlement"),
    "Refunds": PaystackEndpointConfig(path="/refund"),
    "Transfers": PaystackEndpointConfig(path="/transfer"),
    "TransferRecipients": PaystackEndpointConfig(path="/transferrecipient"),
    "Disputes": PaystackEndpointConfig(path="/dispute"),
    "Subaccounts": PaystackEndpointConfig(path="/subaccount"),
    "PaymentPages": PaystackEndpointConfig(path="/page"),
    "TransactionSplits": PaystackEndpointConfig(path="/split", page_size_param="per_page"),
    "BalanceLedger": PaystackEndpointConfig(path="/balance/ledger"),
    "SettlementTransactions": PaystackEndpointConfig(
        path="/settlement/{settlement_id}/transactions",
        # A transaction id is unique on its own, but the key is scoped to the settlement so the
        # table stays unique even if Paystack ever lists one transaction under two settlements.
        primary_keys=["settlement_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="Settlements",
            resolve_param="settlement_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "settlement_id"},
        ),
    ),
    # The page size is left at Paystack's default because the endpoint documents no maximum.
    "DirectDebitMandateAuthorizations": PaystackEndpointConfig(
        path="/directdebit/mandate-authorizations", cursor_paginated=True
    ),
}

ENDPOINTS = tuple(PAYSTACK_ENDPOINTS.keys())
