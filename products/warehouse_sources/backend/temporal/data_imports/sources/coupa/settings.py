from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Coupa hard-caps GET responses at 50 records per page.
PAGE_SIZE = 50

_UPDATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class CoupaEndpointConfig:
    name: str
    # Path under {instance}/api.
    path: str
    # OAuth scope minted for this endpoint only, so OIDC clients granted a
    # subset of per-object scopes can still sync the streams they cover.
    scope: str
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_UPDATED_AT_INCREMENTAL_FIELDS))


# Every stream filters server-side on updated_at[gt] (bracket-notation
# filters), so they're all honestly incremental. Tables documented as having
# unreliable updated_at bumps (e.g. budget_lines) are deliberately excluded.
COUPA_ENDPOINTS: dict[str, CoupaEndpointConfig] = {
    "invoices": CoupaEndpointConfig(
        name="invoices",
        path="/invoices",
        scope="core.invoice.read",
    ),
    "purchase_orders": CoupaEndpointConfig(
        name="purchase_orders",
        path="/purchase_orders",
        scope="core.purchase_order.read",
    ),
    "requisitions": CoupaEndpointConfig(
        name="requisitions",
        path="/requisitions",
        scope="core.requisition.read",
    ),
    "suppliers": CoupaEndpointConfig(
        name="suppliers",
        path="/suppliers",
        scope="core.supplier.read",
    ),
    "contracts": CoupaEndpointConfig(
        name="contracts",
        path="/contracts",
        scope="core.contract.read",
    ),
    "expense_reports": CoupaEndpointConfig(
        name="expense_reports",
        path="/expense_reports",
        scope="core.expense.read",
    ),
    "users": CoupaEndpointConfig(
        name="users",
        path="/users",
        scope="core.user.read",
    ),
    "approvals": CoupaEndpointConfig(
        name="approvals",
        path="/approvals",
        scope="core.approval.read",
    ),
}

ENDPOINTS = tuple(COUPA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COUPA_ENDPOINTS.items() if config.incremental_fields
}
