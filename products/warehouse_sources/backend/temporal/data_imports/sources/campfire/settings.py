from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CAMPFIRE_BASE_URL = "https://api.meetcampfire.com"

DEFAULT_PAGE_SIZE = 500

# (connect, read) seconds. Without it a stalled Campfire response holds an import worker forever.
REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)

# Every incremental-capable Campfire list endpoint filters on the same server-side
# `last_modified_at__gte` param (ISO 8601), documented to cover both active and deleted records.
LAST_MODIFIED_AT = "last_modified_at"
LAST_MODIFIED_AT_PARAM = "last_modified_at__gte"
LAST_MODIFIED_AT_FIELD: list[IncrementalField] = [
    {
        "label": LAST_MODIFIED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": LAST_MODIFIED_AT,
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
    # False for the endpoints that return a bare JSON array and document no page-size or
    # pagination params, so rows arrive in one response and `limit` would be undocumented.
    paginated: bool = True
    page_size: int = DEFAULT_PAGE_SIZE
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
    # Set where the endpoint is only reachable per parent record, so rows are collected by
    # iterating the parent listing first.
    fanout: DependentEndpointConfig | None = None

    @property
    def data_selector(self) -> str:
        # DRF list endpoints wrap rows in `results`; the unpaginated ones return a bare array.
        return "results" if self.paginated else "$"

    @property
    def default_incremental_field(self) -> str | None:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


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
    # Legal entities. Returns every entity in one bare array, with no page-size or
    # last_modified filter documented, so this table is full refresh only.
    "chart_entities": CampfireEndpointConfig(
        name="chart_entities",
        path="/coa/api/entity",
        paginated=False,
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
    # Subscription schedules hang off a contract, so there is no account-wide listing: the
    # rows are collected by walking `contracts` and fetching each contract's subscriptions.
    "contract_subscriptions": CampfireEndpointConfig(
        name="contract_subscriptions",
        path="/rr/api/v1/contracts/{contract_id}/subscriptions",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
        partition_key="created_at",
        paginated=False,
        # `id` is scoped per contract as far as the docs commit to, and every row carries the
        # contract it belongs to.
        primary_keys=["contract", "id"],
        fanout=DependentEndpointConfig(
            parent_name="contracts",
            resolve_param="contract_id",
            resolve_field="id",
            include_from_parent=[],
            # The child takes no page-size param, so the parent listing asks for its own.
            parent_params={"limit": DEFAULT_PAGE_SIZE},
        ),
    ),
    "products": CampfireEndpointConfig(
        name="products",
        path="/rr/api/v1/product",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
        partition_key="created_at",
    ),
    "customers": CampfireEndpointConfig(
        name="customers",
        path="/rr/api/v1/customers",
        incremental_fields=LAST_MODIFIED_AT_FIELD,
        partition_key="created_at",
    ),
}


ENDPOINTS = tuple(CAMPFIRE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CAMPFIRE_ENDPOINTS.items()
}


def probe_path(schema_name: str) -> str | None:
    """The path a credential probe should call for a schema, or None when it is not a schema.

    A fan-out child's path carries an unresolved parent placeholder, so its parent listing is
    probed instead.
    """
    config = CAMPFIRE_ENDPOINTS.get(schema_name)
    if config is None:
        return None
    if config.fanout is not None:
        return CAMPFIRE_ENDPOINTS[config.fanout.parent_name].path
    return config.path
