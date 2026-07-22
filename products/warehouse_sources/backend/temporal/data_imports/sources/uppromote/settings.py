from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

UPPROMOTE_BASE_URL = "https://aff-api.uppromote.com/api/v2"

# The docs don't state a per_page cap; the API is a Laravel-style paginator whose examples use
# small values. 100 keeps request counts low without being an outlandish page size.
UPPROMOTE_PAGE_SIZE = 100

# Maps PostHog webhook-backed schema name -> the logical UpPromote object type used to route
# incoming webhook payloads into the right warehouse table (payloads carry no event name, so the
# hog function derives the type from the payload shape).
RESOURCE_TO_UPPROMOTE_OBJECT_TYPE: dict[str, str] = {
    "affiliates": "affiliate",
    "referrals": "referral",
    "payments_paid": "payment",
}

# The `*.status-changed` events are intentionally not subscribed: their payload is a
# {previous_status, current_status} diff, not the full object, so it can't be merged into the
# table on the primary key. Status changes reconcile on the next pull sync instead.
UPPROMOTE_OBJECT_TYPE_TO_EVENTS: dict[str, tuple[str, ...]] = {
    "affiliate": ("affiliate.new", "affiliate.approved", "affiliate.inactive"),
    "referral": ("referral.new", "referral.approved", "referral.denied"),
    "payment": ("payment.paid",),
}


@dataclass
class UpPromoteEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Whether the endpoint accepts the `from_date`/`to_date` creation-time window params
    # (ISO 8601 UTC). UpPromote has no updated-at cursor, so this is the only server-side
    # incremental filter available.
    supports_date_window: bool = False
    # Referrals reject `from_date` without `to_date` ("required with to_date"), so both are sent.
    requires_to_date: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning; never a mutable timestamp.
    partition_key: Optional[str] = None


_CREATED_AT_FIELD: IncrementalField = {
    "label": "created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at",
    "field_type": IncrementalFieldType.DateTime,
}

_PROCESSED_AT_FIELD: IncrementalField = {
    "label": "processed_at",
    "type": IncrementalFieldType.DateTime,
    "field": "processed_at",
    "field_type": IncrementalFieldType.DateTime,
}

UPPROMOTE_ENDPOINTS: dict[str, UpPromoteEndpointConfig] = {
    "programs": UpPromoteEndpointConfig(
        # No date filter on /programs and the table is small — full refresh only.
        name="programs",
        path="/programs",
        partition_key=None,
    ),
    "affiliates": UpPromoteEndpointConfig(
        name="affiliates",
        path="/affiliates",
        supports_date_window=True,
        incremental_fields=[_CREATED_AT_FIELD],
        partition_key="created_at",
    ),
    "coupons": UpPromoteEndpointConfig(
        name="coupons",
        path="/coupons",
        supports_date_window=True,
        incremental_fields=[_CREATED_AT_FIELD],
        partition_key="created_at",
    ),
    "referrals": UpPromoteEndpointConfig(
        name="referrals",
        path="/referrals",
        supports_date_window=True,
        requires_to_date=True,
        incremental_fields=[_CREATED_AT_FIELD],
        partition_key="created_at",
    ),
    "payments_paid": UpPromoteEndpointConfig(
        name="payments_paid",
        path="/payments/paid",
        primary_keys=["payment_id"],
        supports_date_window=True,
        # Paid-payment rows are created when the payout is processed, so the creation-time
        # window effectively filters on `processed_at` — the only timestamp on the row.
        incremental_fields=[_PROCESSED_AT_FIELD],
        partition_key="processed_at",
    ),
    "payments_unpaid": UpPromoteEndpointConfig(
        # Aggregated outstanding-commission snapshot per affiliate; no id or timestamp fields,
        # so it's a full-refresh-only table keyed on the affiliate.
        name="payments_unpaid",
        path="/payments/unpaid",
        primary_keys=["affiliate_id"],
        partition_key=None,
    ),
}

ENDPOINTS = tuple(UPPROMOTE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in UPPROMOTE_ENDPOINTS.items()
}
