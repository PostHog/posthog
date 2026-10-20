from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField

FLUTTERWAVE_API_V3 = "v3"
FLUTTERWAVE_API_V4 = "v4"

# Flutterwave v3's only server-side timestamp filter is the `from`/`to` window over each record's
# `created_at`, and the API exposes no `updated_at` cursor. Transactions, settlements, refunds,
# transfers, chargebacks, and payment plans all keep mutating after they are created (statuses flip,
# refunds and chargebacks resolve, plans get cancelled), so a `created_at` watermark would advance
# past those rows and never reread the later lifecycle change, leaving the warehouse permanently
# stale. Until Flutterwave exposes an update cursor, every endpoint here syncs as full refresh so the
# merge always sees each record's current state. v4 keeps the same `created_at`-style window (now
# `created_datetime`) and adds no update cursor, so the same holds there.


@dataclass(frozen=True)
class FlutterwaveEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # `created_at` is stamped when the record is written and never moves, so it partitions cleanly by
    # month for an efficient merge.
    partition_key: Optional[str] = "created_at"
    # /transactions documents `from` and `to` as required, so the floor window is sent on every run.
    requires_date_window: bool = False
    data_selector: str = "data"
    # None marks an endpoint that returns its whole list in one response.
    total_pages_path: Optional[str] = "meta.page_info.total_pages"
    params: dict[str, Any] = field(default_factory=dict)
    # The endpoint is queried once per combination of values of these parameters, and each row carries them.
    fan_out_params: tuple[str, ...] = ()


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
    # Reference list of the banks and mobile money providers each payout country supports, used to
    # resolve bank codes on transfers and beneficiaries. The list carries no timestamp.
    "banks": FlutterwaveEndpointConfig(
        name="banks",
        path="/banks/{country}",
        primary_keys=["country", "id"],
        partition_key=None,
        total_pages_path=None,
        params={"include_provider_type": 1},
        fan_out_params=("country",),
    ),
    # Credits and debits on the merchant wallet. `from`, `to` and `currency` are all required, so the
    # endpoint is queried once per wallet currency and direction over the full history window. A
    # statement line has no id: one reference can show up as a debit and later as its reversal credit.
    "wallet_statement": FlutterwaveEndpointConfig(
        name="wallet_statement",
        path="/wallet/statement",
        primary_keys=["currency", "reference", "type", "date"],
        partition_key="date",
        requires_date_window=True,
        data_selector="data.transactions",
        total_pages_path="data.page_info.total_pages",
        params={"include_transaction_type": "true", "include_payout_id": "true"},
        fan_out_params=("currency", "type"),
    ),
    # Airtime, data, cable and utility bills. `status` defaults to Successful, so each status is read.
    "bill_payments": FlutterwaveEndpointConfig(
        name="bill_payments",
        path="/bills/history",
        partition_key="transaction_date",
        requires_date_window=True,
        fan_out_params=("status",),
    ),
}

# The payout countries the v3 banks reference documents.
BANK_COUNTRIES = ("NG", "GH", "KE", "UG", "ZA", "TZ")

# `type` defaults to credit, so both directions are read.
WALLET_STATEMENT_TYPES = ("C", "D")

BILL_PAYMENT_STATUSES = ("Successful", "Failed", "Reversed")

ENDPOINTS = tuple(FLUTTERWAVE_ENDPOINTS.keys())


@dataclass(frozen=True)
class FlutterwaveV4EndpointConfig:
    path: str
    partition_key: Optional[str] = "created_datetime"
    # v4 lists transfers and recipients behind a `next` cursor and nests the rows under this key of
    # `data`; every other list is page-numbered with the rows directly in `data`.
    cursor_data_key: Optional[str] = None
    # Sent only where the reference allows it for both the `size` parameter and the response array.
    page_size: Optional[int] = None


# Table names stay identical to v3 so a table keeps its name across versions; only the vendor path
# differs. v4 has no payment plan, subscription, or subaccount endpoints, so those tables exist only
# on v3.
FLUTTERWAVE_V4_ENDPOINTS: dict[str, FlutterwaveV4EndpointConfig] = {
    "transactions": FlutterwaveV4EndpointConfig(path="/charges"),
    "settlements": FlutterwaveV4EndpointConfig(path="/settlements"),
    "refunds": FlutterwaveV4EndpointConfig(path="/refunds"),
    "transfers": FlutterwaveV4EndpointConfig(path="/transfers", cursor_data_key="transfers", page_size=50),
    "chargebacks": FlutterwaveV4EndpointConfig(path="/chargebacks"),
    # A v4 recipient carries no creation timestamp, so the table is not partitioned.
    "beneficiaries": FlutterwaveV4EndpointConfig(
        path="/transfers/recipients", partition_key=None, cursor_data_key="recipients"
    ),
}

V4_ENDPOINTS = tuple(FLUTTERWAVE_V4_ENDPOINTS.keys())

# No endpoint syncs incrementally on either version (see the module comment above), so the schema builder receives an
# empty map and advertises every table as full-refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
