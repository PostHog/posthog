from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CAMPFIRE_BASE_URL = "https://api.meetcampfire.com"

# Every incremental-capable Campfire list endpoint filters on the same server-side
# `last_modified_at__gte` param (ISO 8601), documented to cover both active and deleted records.
LAST_MODIFIED_AT_FIELD: list[IncrementalField] = [
    {
        "label": "last_modified_at",
        "type": IncrementalFieldType.DateTime,
        "field": "last_modified_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class CampfireEndpointConfig:
    name: str
    path: str
    # Non-empty only where the API documents a server-side `last_modified_at__gte` filter.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable created-at style field confirmed present in the endpoint's response schema.
    partition_key: str | None = None
    page_size: int = 500
    # Opt into DRF cursor pagination: pass an empty `cursor=` on the first request and follow
    # the `next` link. Recommended by Campfire for large/syncing endpoints.
    use_cursor: bool = False
    # "asc" only where Campfire documents a stable ascending order on the incremental field
    # (the payment sync endpoints order by (last_modified_at, id) ascending). Everywhere else
    # the response order is not documented, so "desc" keeps the pipeline from checkpointing
    # the incremental watermark until the sync completes.
    sort_mode: SortMode = "desc"
    # Extra query params sent on the first request (e.g. all_time=true to escape the
    # endpoint's default six-month date window).
    extra_params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


CAMPFIRE_ENDPOINTS: dict[str, CampfireEndpointConfig] = {
    # Campfire's GL transaction log; the recommended endpoint for row-level GL data.
    # Without all_time=true the endpoint defaults to roughly the last six months.
    "chart_transactions": CampfireEndpointConfig(
        name="chart_transactions",
        path="/coa/api/transaction",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
        page_size=1000,
        use_cursor=True,
        extra_params={"all_time": "true"},
    ),
    "journal_entries": CampfireEndpointConfig(
        name="journal_entries",
        path="/coa/api/journal_entry",
        partition_key="created_at",
        extra_params={"all_time": "true"},
    ),
    "invoices": CampfireEndpointConfig(
        name="invoices",
        path="/coa/api/v1/invoice/",
        partition_key="created_at",
    ),
    "invoice_payments": CampfireEndpointConfig(
        name="invoice_payments",
        path="/coa/api/v1/invoice-payments",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
        partition_key="created_at",
        use_cursor=True,
        sort_mode="asc",
    ),
    "credit_memos": CampfireEndpointConfig(
        name="credit_memos",
        path="/coa/api/v1/credit-memo",
        partition_key="created_at",
    ),
    "bills": CampfireEndpointConfig(
        name="bills",
        path="/coa/api/v1/bill/",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
    ),
    "bill_payments": CampfireEndpointConfig(
        name="bill_payments",
        path="/coa/api/v1/bill-payments",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
        partition_key="created_at",
        use_cursor=True,
        sort_mode="asc",
    ),
    "debit_memos": CampfireEndpointConfig(
        name="debit_memos",
        path="/coa/api/v1/debit-memo",
        partition_key="created_at",
    ),
    "bank_accounts": CampfireEndpointConfig(
        name="bank_accounts",
        path="/ca/api/account",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
    ),
    "bank_transactions": CampfireEndpointConfig(
        name="bank_transactions",
        path="/ca/api/transaction",
        partition_key="created_at",
    ),
    "vendors": CampfireEndpointConfig(
        name="vendors",
        path="/coa/api/vendor",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
    ),
    "departments": CampfireEndpointConfig(
        name="departments",
        path="/coa/api/department",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
    ),
    "chart_of_accounts": CampfireEndpointConfig(
        name="chart_of_accounts",
        path="/coa/api/account",
    ),
    "contracts": CampfireEndpointConfig(
        name="contracts",
        path="/rr/api/v1/contracts",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
    ),
    "revenue_transactions": CampfireEndpointConfig(
        name="revenue_transactions",
        path="/rr/api/v1/transactions",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(CAMPFIRE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CAMPFIRE_ENDPOINTS.items()
}
