from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Maps our schema/endpoint name to the API resource path segment and merge primary key.
# All ids are account-wide unique (no fan-out), so every endpoint uses a plain "id" key.
ENDPOINTS = (
    "Customers",
    "Payments",
    "Subscriptions",
    "Transfers",
    "Installments",
)

TABLE_NAMES: dict[str, str] = {
    "Customers": "customers",
    "Payments": "payments",
    "Subscriptions": "subscriptions",
    "Transfers": "transfers",
    "Installments": "installments",
}

# A stable, never-mutated per-row field to partition on for every endpoint.
PARTITION_KEYS: dict[str, str] = {
    "Customers": "dateCreated",
    "Payments": "dateCreated",
    "Subscriptions": "dateCreated",
    "Transfers": "dateCreated",
    "Installments": "dateCreated",
}

# Only endpoints that document a server-side `dateCreated[ge]` range filter are incremental.
# Customers, Subscriptions, and Installments only accept `offset`/`limit` plus non-date
# filters, so a client-side "since" cursor there would still re-fetch every page every run.
INCREMENTAL_DATE_PARAM = "dateCreated[ge]"

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Payments": [
        {
            "label": "dateCreated",
            "type": IncrementalFieldType.Date,
            "field": "dateCreated",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "Transfers": [
        {
            "label": "dateCreated",
            "type": IncrementalFieldType.Date,
            "field": "dateCreated",
            "field_type": IncrementalFieldType.Date,
        },
    ],
}
