from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

MERCURY_BASE_URL = "https://api.mercury.com/api/v1"

# Mercury allows limit between 1 and 1000 (default 1000). Kept below the max so a page of
# wide transaction rows stays comfortably sized.
DEFAULT_PAGE_SIZE = 500

# Pending transactions change status/postedAt for a while after creation, and incremental
# sync cursors on the stable createdAt field. Re-read a trailing window each run so those
# late mutations get merged in.
TRANSACTIONS_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class MercuryEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...] = ("id",)
    # Stable datetime field used for Delta partitioning; None disables partitioning.
    partition_key: str | None = None
    # Cursor-paginated endpoints accept limit/order/start_after; /credit returns one page.
    paginated: bool = True
    # ISO 8601 string columns parsed into timestamps by the rest_source type conversion.
    timestamp_columns: tuple[str, ...] = ()
    # Server-side query param mapped from the user's incremental field, when the API has one.
    incremental_param: str | None = None
    # Body path of the next-page cursor and the query param it is sent back in.
    cursor_path: str = "page.nextPage"
    cursor_param: str = "start_after"
    page_size: int = DEFAULT_PAGE_SIZE
    # Per-account child endpoints, fanned out over a parent account listing.
    fanout: DependentEndpointConfig | None = None
    # Required by the shared fan-out helper; fan-out children here have no server-side time filter.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


MERCURY_ENDPOINTS: dict[str, MercuryEndpointConfig] = {
    "AccountStatements": MercuryEndpointConfig(
        name="AccountStatements",
        path="/account/{accountId}/statements",
        data_selector="statements",
        # Statement rows do not carry their account id, so it is copied in from the parent row.
        primary_keys=("accountId", "id"),
        partition_key="startDate",
        timestamp_columns=("startDate", "endDate"),
        fanout=DependentEndpointConfig(
            parent_name="Accounts",
            resolve_param="accountId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "accountId"},
        ),
    ),
    "Accounts": MercuryEndpointConfig(
        name="Accounts",
        path="/accounts",
        data_selector="accounts",
        partition_key="createdAt",
        timestamp_columns=("createdAt",),
    ),
    "Cards": MercuryEndpointConfig(
        name="Cards",
        path="/cards",
        data_selector="cards",
        partition_key="createdAt",
        timestamp_columns=("createdAt", "updatedAt"),
    ),
    "Categories": MercuryEndpointConfig(
        name="Categories",
        path="/categories",
        data_selector="categories",
    ),
    "CreditAccounts": MercuryEndpointConfig(
        name="CreditAccounts",
        path="/credit",
        data_selector="accounts",
        paginated=False,
        timestamp_columns=("createdAt",),
    ),
    "Customers": MercuryEndpointConfig(
        name="Customers",
        path="/ar/customers",
        data_selector="customers",
        timestamp_columns=("deletedAt",),
    ),
    "Events": MercuryEndpointConfig(
        name="Events",
        path="/events",
        data_selector="events",
        partition_key="occurredAt",
        timestamp_columns=("occurredAt",),
    ),
    "Invoices": MercuryEndpointConfig(
        name="Invoices",
        path="/ar/invoices",
        data_selector="invoices",
        partition_key="createdAt",
        timestamp_columns=("createdAt", "updatedAt", "canceledAt"),
    ),
    "Merchants": MercuryEndpointConfig(
        name="Merchants",
        path="/merchants",
        data_selector="data",
    ),
    "Recipients": MercuryEndpointConfig(
        name="Recipients",
        path="/recipients",
        data_selector="recipients",
    ),
    "Transactions": MercuryEndpointConfig(
        name="Transactions",
        path="/transactions",
        data_selector="transactions",
        partition_key="createdAt",
        timestamp_columns=("createdAt", "postedAt", "failedAt"),
        # `start` filters on the earliest createdAt to include, per the Mercury API docs.
        incremental_param="start",
    ),
    "TreasuryAccounts": MercuryEndpointConfig(
        name="TreasuryAccounts",
        path="/treasury",
        data_selector="accounts",
        timestamp_columns=("createdAt",),
    ),
    "TreasuryStatements": MercuryEndpointConfig(
        name="TreasuryStatements",
        path="/treasury/{treasuryId}/statements",
        data_selector="statements",
        primary_keys=("accountId", "id"),
        partition_key="createdAt",
        timestamp_columns=("createdAt", "updatedAt", "creationDate"),
        fanout=DependentEndpointConfig(
            parent_name="TreasuryAccounts",
            resolve_param="treasuryId",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    "TreasuryTransactions": MercuryEndpointConfig(
        name="TreasuryTransactions",
        path="/treasury/{treasuryId}/transactions",
        data_selector="transactions",
        primary_keys=("accountId", "id"),
        # Unlike the other list endpoints, this one pages with an integer `cursor` in the body.
        cursor_path="cursor",
        cursor_param="cursor",
        fanout=DependentEndpointConfig(
            parent_name="TreasuryAccounts",
            resolve_param="treasuryId",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    "Users": MercuryEndpointConfig(
        name="Users",
        path="/users",
        data_selector="users",
        primary_keys=("userId",),
    ),
}

ENDPOINTS = tuple(MERCURY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    # Only /transactions exposes a server-side timestamp filter (`start`/`end` on createdAt).
    # The other endpoints are small dimension lists synced with full refresh.
    "Transactions": [incremental_field("createdAt")],
}
