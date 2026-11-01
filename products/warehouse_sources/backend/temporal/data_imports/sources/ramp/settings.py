from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Scopes requested when validating a new connection. Scopes are fixed on the
# developer app at creation, so the caption tells users to grant these.
TOKEN_SCOPES = "transactions:read reimbursements:read users:read cards:read departments:read"
# Ramp list pages cap at 100 items.
PAGE_SIZE = 100


@dataclass
class RampEndpointConfig:
    name: str
    # Path under {host}/developer/v1.
    path: str
    # The token for a sync requests only this scope: Ramp rejects a mint that asks for a
    # scope the app lacks, so an app without a newer scope still syncs its other tables.
    scope: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param that pushes the incremental cursor server-side.
    incremental_param: Optional[str] = None
    # Stable event-time field used for datetime partitioning.
    partition_key: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    default_incremental_field: Optional[str] = None


_VENDORS_FANOUT = DependentEndpointConfig(
    parent_name="vendors",
    resolve_param="vendor_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "vendor_id"},
)


RAMP_ENDPOINTS: dict[str, RampEndpointConfig] = {
    "transactions": RampEndpointConfig(
        name="transactions",
        path="/transactions",
        scope="transactions:read",
        partition_key="user_transaction_time",
        # from_date filters on the transaction time. There is no updated_after,
        # so late state changes (pending→cleared) need an occasional full
        # refresh — the same trade-off Fivetran makes.
        incremental_param="from_date",
        incremental_fields=[
            {
                "label": "user_transaction_time",
                "type": IncrementalFieldType.DateTime,
                "field": "user_transaction_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "reimbursements": RampEndpointConfig(
        name="reimbursements",
        path="/reimbursements",
        scope="reimbursements:read",
    ),
    "users": RampEndpointConfig(
        name="users",
        path="/users",
        scope="users:read",
    ),
    "cards": RampEndpointConfig(
        name="cards",
        path="/cards",
        scope="cards:read",
    ),
    "departments": RampEndpointConfig(
        name="departments",
        path="/departments",
        scope="departments:read",
    ),
    # Bills and vendors change after creation (payment status, approvals, details), but the
    # bills endpoints only filter on created_at and vendors.updated_at is nullable, so these
    # lookups stay full refresh rather than risk silently missing changed or new rows.
    "vendors": RampEndpointConfig(
        name="vendors",
        path="/vendors",
        scope="vendors:read",
        partition_key="created_at",
    ),
    "vendor_contacts": RampEndpointConfig(
        name="vendor_contacts",
        path="/vendors/{vendor_id}/contacts",
        scope="vendors:read",
        # Contact rows carry no vendor reference of their own.
        primary_keys=["vendor_id", "id"],
        fanout=_VENDORS_FANOUT,
    ),
    "merchants": RampEndpointConfig(
        name="merchants",
        path="/merchants",
        scope="merchants:read",
    ),
    "bills": RampEndpointConfig(
        name="bills",
        path="/bills",
        scope="bills:read",
        partition_key="created_at",
    ),
    "bill_drafts": RampEndpointConfig(
        name="bill_drafts",
        path="/bills/drafts",
        scope="bills:read",
        partition_key="created_at",
    ),
    "accounting_accounts": RampEndpointConfig(
        name="accounting_accounts",
        path="/accounting/accounts",
        scope="accounting:read",
        # `id` is the ERP's remote ID and can be absent; `ramp_id` is Ramp's own unique ID.
        primary_keys=["ramp_id"],
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(RAMP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RAMP_ENDPOINTS.items() if config.incremental_fields
}
