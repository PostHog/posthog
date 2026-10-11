from dataclasses import dataclass

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
    primary_key: str = "id"
    # Stable datetime field used for Delta partitioning; None disables partitioning.
    partition_key: str | None = None
    # Cursor-paginated endpoints accept limit/order/start_after; /credit returns one page.
    paginated: bool = True
    # ISO 8601 string columns parsed into timestamps by the rest_source type conversion.
    timestamp_columns: tuple[str, ...] = ()
    # Server-side query param mapped from the user's incremental field, when the API has one.
    incremental_param: str | None = None


MERCURY_ENDPOINTS: dict[str, MercuryEndpointConfig] = {
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
    "Users": MercuryEndpointConfig(
        name="Users",
        path="/users",
        data_selector="users",
        primary_key="userId",
    ),
}

ENDPOINTS = tuple(MERCURY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    # Only /transactions exposes a server-side timestamp filter (`start`/`end` on createdAt).
    # The other endpoints are small dimension lists synced with full refresh.
    "Transactions": [incremental_field("createdAt")],
}
