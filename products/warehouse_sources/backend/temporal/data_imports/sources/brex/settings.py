from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class BrexEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Server-side timestamp filter query param (RFC 3339 date-time, "on or after" semantics).
    incremental_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field used for partitioning. Never an updated_at-style field, which
    # would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # When True, the endpoint is paged once per cash account listed from /v2/accounts/cash,
    # with `{account_id}` in the path resolved per account.
    fan_out_cash_accounts: bool = False


# Brex splits its data across sub-APIs (Transactions, Expenses, Team, Payments, Budgets) that
# all share the same host, bearer auth, and cursor pagination (`cursor` + `limit` params,
# `next_cursor` + `items` in the response body).
#
# Incremental sync is only advertised where Brex exposes a server-side timestamp filter:
# transactions support `posted_at_start` (filters on `posted_at_date`) and expenses support
# `updated_at_start` (filters on `updated_at`). Team/vendors/budgets endpoints have no such
# filter, so they are full refresh only.
BREX_ENDPOINTS: dict[str, BrexEndpointConfig] = {
    "card_transactions": BrexEndpointConfig(
        name="card_transactions",
        path="/v2/transactions/card/primary",
        incremental_param="posted_at_start",
        partition_key="posted_at_date",
        incremental_fields=[
            {
                "label": "posted_at_date",
                "type": IncrementalFieldType.Date,
                "field": "posted_at_date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "cash_transactions": BrexEndpointConfig(
        name="cash_transactions",
        path="/v2/transactions/cash/{account_id}",
        # Transaction ids are likely globally unique, but the docs don't guarantee it across
        # cash accounts, so the injected account id is part of the composite key.
        primary_keys=["account_id", "id"],
        incremental_param="posted_at_start",
        partition_key="posted_at_date",
        fan_out_cash_accounts=True,
        incremental_fields=[
            {
                "label": "posted_at_date",
                "type": IncrementalFieldType.Date,
                "field": "posted_at_date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "expenses": BrexEndpointConfig(
        name="expenses",
        path="/v1/expenses",
        incremental_param="updated_at_start",
        # No partition key: the only stable datetime candidates (purchased_at, submitted_at)
        # are nullable on the expense object.
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "users": BrexEndpointConfig(
        name="users",
        path="/v2/users",
    ),
    "departments": BrexEndpointConfig(
        name="departments",
        path="/v2/departments",
    ),
    "locations": BrexEndpointConfig(
        name="locations",
        path="/v2/locations",
    ),
    "vendors": BrexEndpointConfig(
        name="vendors",
        path="/v1/vendors",
    ),
    "budgets": BrexEndpointConfig(
        name="budgets",
        path="/v2/budgets",
        primary_keys=["budget_id"],
    ),
}

ENDPOINTS = tuple(BREX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BREX_ENDPOINTS.items() if config.incremental_fields
}
