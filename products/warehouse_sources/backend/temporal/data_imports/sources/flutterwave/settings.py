from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class FlutterwaveEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # `created_at` is stamped when the record is written and never moves, so it is safe both as the
    # partition key and (where the endpoint accepts the date window) as the incremental cursor.
    partition_key: Optional[str] = "created_at"
    # True only for endpoints documented to accept the `from`/`to` (YYYY-MM-DD) window, which is
    # Flutterwave v3's only server-side timestamp filter. Everything else ships full refresh.
    supports_date_window: bool = False
    # /transactions documents `from` and `to` as required, so the window is sent on every run,
    # full-refresh included, rather than only when syncing incrementally.
    requires_date_window: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Flutterwave v3 exposes no sort parameter and returns the most recent record on page 1, so rows
    # arrive newest-first. Declaring `asc` would checkpoint the watermark at ~now after the first
    # batch and silently drop the older rows still to come.
    sort_mode: Literal["asc", "desc"] = "desc"


def _created_at_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


FLUTTERWAVE_ENDPOINTS: dict[str, FlutterwaveEndpointConfig] = {
    # Every payment collected on the account. `from`/`to` are documented as required here.
    "transactions": FlutterwaveEndpointConfig(
        name="transactions",
        path="/transactions",
        supports_date_window=True,
        requires_date_window=True,
        incremental_fields=_created_at_incremental_fields(),
    ),
    # Payouts of collected funds to the merchant's settlement account.
    "settlements": FlutterwaveEndpointConfig(
        name="settlements",
        path="/settlements",
        supports_date_window=True,
        incremental_fields=_created_at_incremental_fields(),
    ),
    # Money returned to customers against a previously successful charge.
    "refunds": FlutterwaveEndpointConfig(
        name="refunds",
        path="/refunds",
        supports_date_window=True,
        incremental_fields=_created_at_incremental_fields(),
    ),
    # Outbound payouts initiated by the merchant.
    "transfers": FlutterwaveEndpointConfig(
        name="transfers",
        path="/transfers",
        supports_date_window=True,
        incremental_fields=_created_at_incremental_fields(),
    ),
    # Customer-initiated payment disputes.
    "chargebacks": FlutterwaveEndpointConfig(
        name="chargebacks",
        path="/chargebacks",
        supports_date_window=True,
        incremental_fields=_created_at_incremental_fields(),
    ),
    # Recurring billing plan definitions.
    "payment_plans": FlutterwaveEndpointConfig(
        name="payment_plans",
        path="/payment-plans",
        supports_date_window=True,
        incremental_fields=_created_at_incremental_fields(),
    ),
    # Customer enrolments against a payment plan. The only date filters are `subscribed_from` /
    # `subscribed_to`, which filter the subscription date rather than the row's `created_at`, so
    # this ships full refresh rather than guessing that the two line up.
    "subscriptions": FlutterwaveEndpointConfig(
        name="subscriptions",
        path="/subscriptions",
    ),
    # Collection subaccounts used for split payments. Paginated but not date-filterable.
    "subaccounts": FlutterwaveEndpointConfig(
        name="subaccounts",
        path="/subaccounts",
    ),
    # Saved payout recipients. Paginated but not date-filterable.
    "beneficiaries": FlutterwaveEndpointConfig(
        name="beneficiaries",
        path="/beneficiaries",
    ),
}

ENDPOINTS = tuple(FLUTTERWAVE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FLUTTERWAVE_ENDPOINTS.items()
}
