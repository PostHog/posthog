from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

# Mollie list pages cap at 250 items.
PAGE_SIZE = 250


@dataclass(frozen=True)
class MollieEndpointConfig:
    name: str
    path: str
    # Key the rows live under inside the HAL `_embedded` object.
    embedded_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Every Mollie resource carries an immutable createdAt.
    partition_key: str = "createdAt"
    page_size: int = PAGE_SIZE
    incremental_fields: list[str] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Set for endpoints nested under a parent resource (e.g. /customers/{customerId}/mandates).
    fanout: DependentEndpointConfig | None = None


# No Mollie v2 list endpoint supports created/updated-since filtering — only an
# ID-cursor (`from` + `_links.next`), and mutable objects (payments, refunds,
# chargebacks) change status for days after creation — so every stream is an
# honest full refresh. ID-anchored next links make pagination drift-safe.
MOLLIE_ENDPOINTS: dict[str, MollieEndpointConfig] = {
    "payments": MollieEndpointConfig(
        name="payments",
        path="/payments",
        embedded_key="payments",
    ),
    "refunds": MollieEndpointConfig(
        name="refunds",
        path="/refunds",
        embedded_key="refunds",
    ),
    "chargebacks": MollieEndpointConfig(
        name="chargebacks",
        path="/chargebacks",
        embedded_key="chargebacks",
    ),
    "customers": MollieEndpointConfig(
        name="customers",
        path="/customers",
        embedded_key="customers",
    ),
    "subscriptions": MollieEndpointConfig(
        name="subscriptions",
        path="/subscriptions",
        embedded_key="subscriptions",
    ),
    "settlements": MollieEndpointConfig(
        name="settlements",
        path="/settlements",
        embedded_key="settlements",
    ),
    "payment_links": MollieEndpointConfig(
        name="payment_links",
        path="/payment-links",
        embedded_key="payment_links",
    ),
    "payouts": MollieEndpointConfig(
        name="payouts",
        path="/payouts",
        embedded_key="payouts",
    ),
    # Balances, balance transactions, settlements, settlement payments, invoices and profiles are
    # organization-level resources: Mollie serves them only to access tokens, never to a profile API key.
    "invoices": MollieEndpointConfig(
        name="invoices",
        path="/invoices",
        embedded_key="invoices",
        # Invoices carry no createdAt; issuedAt is the fixed invoice date.
        partition_key="issuedAt",
    ),
    "balances": MollieEndpointConfig(
        name="balances",
        path="/balances",
        embedded_key="balances",
    ),
    "balance_transactions": MollieEndpointConfig(
        name="balance_transactions",
        path="/balances/{balanceId}/transactions",
        embedded_key="balance_transactions",
        # Transaction rows don't carry their balance id, so it comes from the parent row.
        primary_keys=["balanceId", "id"],
        fanout=DependentEndpointConfig(
            parent_name="balances",
            resolve_param="balanceId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "balanceId"},
        ),
    ),
    "settlement_payments": MollieEndpointConfig(
        name="settlement_payments",
        path="/settlements/{settlementId}/payments",
        embedded_key="payments",
        primary_keys=["settlementId", "id"],
        fanout=DependentEndpointConfig(
            parent_name="settlements",
            resolve_param="settlementId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "settlementId"},
        ),
    ),
    "profiles": MollieEndpointConfig(
        name="profiles",
        path="/profiles",
        embedded_key="profiles",
    ),
    "mandates": MollieEndpointConfig(
        name="mandates",
        path="/customers/{customerId}/mandates",
        embedded_key="mandates",
        primary_keys=["customerId", "id"],
        fanout=DependentEndpointConfig(
            parent_name="customers",
            resolve_param="customerId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "customerId"},
        ),
    ),
    "captures": MollieEndpointConfig(
        name="captures",
        path="/payments/{paymentId}/captures",
        embedded_key="captures",
        primary_keys=["paymentId", "id"],
        fanout=DependentEndpointConfig(
            parent_name="payments",
            resolve_param="paymentId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "paymentId"},
        ),
    ),
}

ENDPOINTS = tuple(MOLLIE_ENDPOINTS.keys())
