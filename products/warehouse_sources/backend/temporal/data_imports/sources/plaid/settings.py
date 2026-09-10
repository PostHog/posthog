from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class PlaidEndpointConfig:
    name: str
    primary_key: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# One PostHog source connects one Plaid Item (the access token the user
# obtained via Plaid Link). Transactions use /transactions/get with the
# server-side start_date filter — /transactions/sync's opaque cursor can't be
# expressed as a row-field watermark in this framework.
PLAID_ENDPOINTS: dict[str, PlaidEndpointConfig] = {
    "accounts": PlaidEndpointConfig(
        name="accounts",
        primary_key="account_id",
    ),
    "transactions": PlaidEndpointConfig(
        name="transactions",
        primary_key="transaction_id",
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
}

ENDPOINTS = tuple(PLAID_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLAID_ENDPOINTS.items() if config.incremental_fields
}
