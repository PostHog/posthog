from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# GoCardless list pages cap at 500 items.
PAGE_SIZE = 500


@dataclass(frozen=True)
class GoCardlessEndpointConfig:
    name: str
    path: str
    # Key the rows live under in the response body (GoCardless wraps per resource).
    data_key: str
    # None for resources with no id, which only ever sync as a full replace.
    primary_key: Optional[str] = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Immutable created_at on every resource that has one; None for resources without it.
    partition_key: Optional[str] = "created_at"
    page_size: int = PAGE_SIZE
    default_incremental_field: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None
    # Bounds the fan-out parent listing to rows created in the last N days.
    parent_created_within_days: Optional[int] = None


# GoCardless list endpoints filter only on created_at (no updated_at), and core
# records (payments, mandates, subscriptions) mutate status over time — so the
# append-only events stream (GoCardless's change log) is the one honest
# incremental, and the mutable tables stay full refresh (the pattern Fivetran
# uses). Lists are reverse-chronological with no sort param.
GOCARDLESS_ENDPOINTS: dict[str, GoCardlessEndpointConfig] = {
    "customers": GoCardlessEndpointConfig(
        name="customers",
        path="/customers",
        data_key="customers",
    ),
    "mandates": GoCardlessEndpointConfig(
        name="mandates",
        path="/mandates",
        data_key="mandates",
    ),
    "payments": GoCardlessEndpointConfig(
        name="payments",
        path="/payments",
        data_key="payments",
    ),
    "subscriptions": GoCardlessEndpointConfig(
        name="subscriptions",
        path="/subscriptions",
        data_key="subscriptions",
    ),
    "payouts": GoCardlessEndpointConfig(
        name="payouts",
        path="/payouts",
        data_key="payouts",
    ),
    "refunds": GoCardlessEndpointConfig(
        name="refunds",
        path="/refunds",
        data_key="refunds",
    ),
    "events": GoCardlessEndpointConfig(
        name="events",
        path="/events",
        data_key="events",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "customer_bank_accounts": GoCardlessEndpointConfig(
        name="customer_bank_accounts",
        path="/customer_bank_accounts",
        data_key="customer_bank_accounts",
    ),
    "creditors": GoCardlessEndpointConfig(
        name="creditors",
        path="/creditors",
        data_key="creditors",
    ),
    # /balances requires a creditor filter, so it fans out over creditors. A balance row has no
    # id or created_at; it is a point-in-time snapshot, so it is replaced on every sync.
    "balances": GoCardlessEndpointConfig(
        name="balances",
        path="/balances?creditor={creditor}",
        data_key="balances",
        primary_key=None,
        partition_key=None,
        fanout=DependentEndpointConfig(
            parent_name="creditors",
            resolve_param="creditor",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "creditor_id"},
        ),
    ),
    # /payout_items requires a payout filter and has no id or created_at, so it fans out over
    # payouts and syncs as a full replace. GoCardless serves items only for payouts created in
    # the last 6 months and answers 410 Gone for older ones, so the parent listing is bounded
    # to that window and a boundary 410 is skipped rather than failing the table.
    "payout_items": GoCardlessEndpointConfig(
        name="payout_items",
        path="/payout_items?payout={payout}",
        data_key="payout_items",
        primary_key=None,
        partition_key=None,
        fanout=DependentEndpointConfig(
            parent_name="payouts",
            resolve_param="payout",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "payout_id"},
            child_response_actions=[{"status_code": 410, "action": "ignore"}],
        ),
        parent_created_within_days=186,
    ),
}

ENDPOINTS = tuple(GOCARDLESS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GOCARDLESS_ENDPOINTS.items() if config.incremental_fields
}
