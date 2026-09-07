from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Flutterwave v3's only server-side timestamp filter is the `from`/`to` window over each record's
# `created_at`, and the API exposes no `updated_at` cursor. Transactions, settlements, refunds,
# transfers, chargebacks, and payment plans all keep mutating after they are created (statuses flip,
# refunds and chargebacks resolve, plans get cancelled), so a `created_at` watermark would advance
# past those rows and never reread the later lifecycle change, leaving the warehouse permanently
# stale. Until Flutterwave exposes an update cursor, every endpoint here syncs as full refresh so the
# merge always sees each record's current state.


@dataclass
class FlutterwaveEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # `created_at` is stamped when the record is written and never moves, so it partitions cleanly by
    # month for an efficient merge.
    partition_key: Optional[str] = "created_at"
    # /transactions documents `from` and `to` as required, so the floor window is sent on every run.
    requires_date_window: bool = False


FLUTTERWAVE_ENDPOINTS: dict[str, FlutterwaveEndpointConfig] = {
    # Every payment collected on the account. `from`/`to` are documented as required here.
    "transactions": FlutterwaveEndpointConfig(
        name="transactions",
        path="/transactions",
        requires_date_window=True,
    ),
    # Payouts of collected funds to the merchant's settlement account.
    "settlements": FlutterwaveEndpointConfig(name="settlements", path="/settlements"),
    # Money returned to customers against a previously successful charge.
    "refunds": FlutterwaveEndpointConfig(name="refunds", path="/refunds"),
    # Outbound payouts initiated by the merchant.
    "transfers": FlutterwaveEndpointConfig(name="transfers", path="/transfers"),
    # Customer-initiated payment disputes.
    "chargebacks": FlutterwaveEndpointConfig(name="chargebacks", path="/chargebacks"),
    # Recurring billing plan definitions.
    "payment_plans": FlutterwaveEndpointConfig(name="payment_plans", path="/payment-plans"),
    # Customer enrolments against a payment plan.
    "subscriptions": FlutterwaveEndpointConfig(name="subscriptions", path="/subscriptions"),
    # Collection subaccounts used for split payments.
    "subaccounts": FlutterwaveEndpointConfig(name="subaccounts", path="/subaccounts"),
    # Saved payout recipients.
    "beneficiaries": FlutterwaveEndpointConfig(name="beneficiaries", path="/beneficiaries"),
}

ENDPOINTS = tuple(FLUTTERWAVE_ENDPOINTS.keys())

# No endpoint syncs incrementally (see the module comment above), so the schema builder receives an
# empty map and advertises every table as full-refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
