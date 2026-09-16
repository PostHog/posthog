from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class BrexFanOutConfig:
    """Pages a child endpoint once per row of a parent endpoint that is also its own table."""

    # Endpoint name of the parent, whose `path` is paged to drive the fan-out.
    parent_name: str
    # Placeholder in the child's `path`, bound from `parent_field` on each parent row.
    resolve_param: str
    parent_field: str
    # Parent field -> the key it lands under on child rows. Empty when the child response
    # already carries the parent identifier, so nothing needs injecting.
    parent_field_renames: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
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
    # Set when the endpoint is paged once per row of a parent endpoint, with the parent's
    # identifier resolved into the child `path`.
    fan_out: Optional[BrexFanOutConfig] = None
    # Response envelope key holding the rows. None when the endpoint returns a bare JSON array.
    data_selector: Optional[str] = "items"
    # False for the endpoints Brex documents no `cursor`/`limit` params on — the whole
    # collection arrives in a single response.
    paginated: bool = True
    # Per-version `path` overrides, keyed by the source's supported version labels. Brex
    # versions each product API independently in the URL (transactions/users on /v2,
    # expenses/vendors on /v1) with no global version header or segment, and every endpoint
    # already targets the current path for its API — so this stays empty until a specific
    # Brex API ships a new path under a new version.
    versioned_paths: dict[str, str] = field(default_factory=dict)


# Brex splits its data across sub-APIs (Transactions, Expenses, Team, Payments, Budgets) that
# all share the same host, bearer auth, and cursor pagination (`cursor` + `limit` params,
# `next_cursor` + `items` in the response body).
#
# Incremental sync is only advertised where Brex exposes a server-side timestamp filter:
# transactions support `posted_at_start` (filters on `posted_at_date`) and expenses support
# `updated_at_start` (filters on `updated_at`). The account, team, payments and budgets
# endpoints have no such filter, so they are full refresh only.
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
        fan_out=BrexFanOutConfig(
            parent_name="cash_accounts",
            resolve_param="account_id",
            parent_field="id",
            parent_field_renames={"id": "account_id"},
        ),
        incremental_fields=[
            {
                "label": "posted_at_date",
                "type": IncrementalFieldType.Date,
                "field": "posted_at_date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "card_accounts": BrexEndpointConfig(
        name="card_accounts",
        path="/v2/accounts/card",
        # The only Brex endpoint that answers with a bare JSON array rather than the
        # `{items, next_cursor}` envelope, and the only one with no pagination params.
        data_selector=None,
        paginated=False,
    ),
    "cash_accounts": BrexEndpointConfig(
        name="cash_accounts",
        # Listed as its own table, and paged as the parent of the cash transactions fan-out.
        path="/v2/accounts/cash",
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
    "titles": BrexEndpointConfig(
        name="titles",
        path="/v2/titles",
    ),
    "cards": BrexEndpointConfig(
        name="cards",
        path="/v2/cards",
        # `user_id` is an optional filter; omitting it lists every card on the account.
        partition_key="created_at",
    ),
    "fields": BrexEndpointConfig(
        name="fields",
        path="/v1/fields",
        # The Fields API keys both fields and field values on `brex_id`, not `id`.
        primary_keys=["brex_id"],
        # No partition key: `updated_at` is the only datetime on the field object, and it
        # moves whenever the field is edited.
    ),
    "field_values": BrexEndpointConfig(
        name="field_values",
        path="/v1/fields/{field_id}/values",
        # Brex documents no uniqueness for `brex_id` across fields, so the parent field id is
        # part of the key. Field value rows already carry `field_id`, so nothing is injected.
        primary_keys=["field_id", "brex_id"],
        fan_out=BrexFanOutConfig(
            parent_name="fields",
            resolve_param="field_id",
            parent_field="brex_id",
        ),
    ),
    "vendors": BrexEndpointConfig(
        name="vendors",
        path="/v1/vendors",
    ),
    "transfers": BrexEndpointConfig(
        name="transfers",
        path="/v1/transfers",
        # No partition key: `created_at` is nullable on the transfer object.
    ),
    "budgets": BrexEndpointConfig(
        name="budgets",
        path="/v2/budgets",
        primary_keys=["budget_id"],
    ),
    "budget_programs": BrexEndpointConfig(
        name="budget_programs",
        path="/v1/budget_programs",
        partition_key="created_at",
    ),
    "spend_limits": BrexEndpointConfig(
        name="spend_limits",
        path="/v2/spend_limits",
        # No partition key: every date field on a spend limit is nullable.
    ),
}

ENDPOINTS = tuple(BREX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BREX_ENDPOINTS.items() if config.incremental_fields
}
