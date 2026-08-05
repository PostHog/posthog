from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GoCardlessEndpointConfig:
    name: str
    path: str
    # Key the rows live under in the response body (GoCardless wraps per resource).
    data_key: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Every GoCardless resource carries an immutable created_at.
    partition_key: str = "created_at"


# GoCardless list endpoints filter only on created_at (no updated_at), and core
# records (payments, mandates, subscriptions) mutate status over time — so the
# append-only events stream (GoCardless's change log) is the one honest
# incremental, and the mutable tables stay full refresh (the pattern Fivetran
# uses). Lists are reverse-chronological with no sort param.
GOCARDLESS_ENDPOINTS: dict[str, GoCardlessEndpointConfig] = {
    "customers": GoCardlessEndpointConfig(
        name="customers",
        path="/customers",
        data_key="customers",
    ),
    "mandates": GoCardlessEndpointConfig(
        name="mandates",
        path="/mandates",
        data_key="mandates",
    ),
    "payments": GoCardlessEndpointConfig(
        name="payments",
        path="/payments",
        data_key="payments",
    ),
    "subscriptions": GoCardlessEndpointConfig(
        name="subscriptions",
        path="/subscriptions",
        data_key="subscriptions",
    ),
    "payouts": GoCardlessEndpointConfig(
        name="payouts",
        path="/payouts",
        data_key="payouts",
    ),
    "refunds": GoCardlessEndpointConfig(
        name="refunds",
        path="/refunds",
        data_key="refunds",
    ),
    "events": GoCardlessEndpointConfig(
        name="events",
        path="/events",
        data_key="events",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(GOCARDLESS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GOCARDLESS_ENDPOINTS.items() if config.incremental_fields
}
