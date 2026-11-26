from dataclasses import dataclass

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

BASE_URL = "https://api.omise.co"

# Documented default and maximum page size for every list endpoint.
PAGE_SIZE = 100

# Latest Omise-Version header value (see https://docs.omise.co/api-versioning).
API_VERSION = "2019-05-29"


@dataclass(frozen=True)
class OpnPaymentsEndpointConfig:
    path: str
    table_name: str
    fanout: DependentEndpointConfig | None = None
    primary_keys: tuple[str, ...] = ("id",)
    incremental: bool = True

    # Read by the shared fan-out helper.
    @property
    def name(self) -> str:
        return self.table_name

    @property
    def page_size(self) -> int:
        return PAGE_SIZE

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return [_created_at_field()] if self.incremental and not self.fanout else []

    @property
    def default_incremental_field(self) -> str | None:
        return "created_at" if self.incremental and not self.fanout else None


def _created_at_field() -> IncrementalField:
    return {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    }


def _per_parent(parent_name: str, parent_id_column: str) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param="parent_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": parent_id_column},
        parent_params={"order": "chronological"},
        child_params={"order": "chronological"},
        # A parent deleted after the parent listing 404s on its child request.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


# Every list endpoint shares the same offset/limit/from/to pagination and documents `created_at`
# as the row-creation timestamp, which never changes afterwards — it doubles as the incremental
# cursor and the partition key for all of them. Fan-out children (one request series per parent)
# arrive in no single order, so they sync with full refresh only.
OPN_PAYMENTS_ENDPOINTS: dict[str, OpnPaymentsEndpointConfig] = {
    "Charges": OpnPaymentsEndpointConfig(path="/charges", table_name="charges"),
    "Customers": OpnPaymentsEndpointConfig(path="/customers", table_name="customers"),
    "Disputes": OpnPaymentsEndpointConfig(path="/disputes", table_name="disputes"),
    "Events": OpnPaymentsEndpointConfig(path="/events", table_name="events"),
    "Receipts": OpnPaymentsEndpointConfig(path="/receipts", table_name="receipts"),
    "Recipients": OpnPaymentsEndpointConfig(path="/recipients", table_name="recipients"),
    "Refunds": OpnPaymentsEndpointConfig(path="/refunds", table_name="refunds"),
    # A schedule's status and upcoming dates change long after its `created_at`, which a
    # `from` filter on that field would never re-read.
    "Schedules": OpnPaymentsEndpointConfig(path="/schedules", table_name="schedules", incremental=False),
    "Transactions": OpnPaymentsEndpointConfig(path="/transactions", table_name="transactions"),
    "Transfers": OpnPaymentsEndpointConfig(path="/transfers", table_name="transfers"),
    "Cards": OpnPaymentsEndpointConfig(
        path="/customers/{parent_id}/cards",
        table_name="cards",
        fanout=_per_parent("Customers", "customer_id"),
        primary_keys=("customer_id", "id"),
    ),
    "Occurrences": OpnPaymentsEndpointConfig(
        path="/schedules/{parent_id}/occurrences",
        table_name="occurrences",
        fanout=_per_parent("Schedules", "schedule_id"),
        primary_keys=("schedule_id", "id"),
    ),
}

ENDPOINTS = tuple(OPN_PAYMENTS_ENDPOINTS.keys())

PARTITION_KEY = "created_at"

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPN_PAYMENTS_ENDPOINTS.items() if config.incremental_fields
}
