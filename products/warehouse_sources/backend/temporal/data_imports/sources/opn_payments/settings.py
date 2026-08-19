from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.omise.co"

# Documented default and maximum page size for every list endpoint.
PAGE_SIZE = 100

# Latest Omise-Version header value (see https://docs.omise.co/api-versioning).
API_VERSION = "2019-05-29"


@dataclass(frozen=True)
class OpnPaymentsEndpointConfig:
    path: str
    table_name: str


# Every top-level list endpoint shares the same offset/limit/from/to pagination and documents
# `created_at` as the row-creation timestamp, which never changes afterwards — it doubles as the
# incremental cursor and the partition key for all of them.
OPN_PAYMENTS_ENDPOINTS: dict[str, OpnPaymentsEndpointConfig] = {
    "Charges": OpnPaymentsEndpointConfig(path="/charges", table_name="charges"),
    "Customers": OpnPaymentsEndpointConfig(path="/customers", table_name="customers"),
    "Disputes": OpnPaymentsEndpointConfig(path="/disputes", table_name="disputes"),
    "Events": OpnPaymentsEndpointConfig(path="/events", table_name="events"),
    "Recipients": OpnPaymentsEndpointConfig(path="/recipients", table_name="recipients"),
    "Refunds": OpnPaymentsEndpointConfig(path="/refunds", table_name="refunds"),
    "Transactions": OpnPaymentsEndpointConfig(path="/transactions", table_name="transactions"),
    "Transfers": OpnPaymentsEndpointConfig(path="/transfers", table_name="transfers"),
}

ENDPOINTS = tuple(OPN_PAYMENTS_ENDPOINTS.keys())

PARTITION_KEY = "created_at"


def _created_at_field() -> IncrementalField:
    return {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    }


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [_created_at_field()] for name in ENDPOINTS}
