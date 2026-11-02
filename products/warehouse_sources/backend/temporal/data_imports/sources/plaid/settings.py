from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class PlaidEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None
    should_sync_default: bool = True
    description: str | None = None


# One PostHog source connects one Plaid Item (the access token the user
# obtained via Plaid Link). Transactions use /transactions/get with the
# server-side start_date filter — /transactions/sync's opaque cursor can't be
# expressed as a row-field watermark in this framework.
PLAID_ENDPOINTS: dict[str, PlaidEndpointConfig] = {
    "accounts": PlaidEndpointConfig(
        name="accounts",
        primary_keys=["account_id"],
    ),
    "transactions": PlaidEndpointConfig(
        name="transactions",
        primary_keys=["transaction_id"],
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
        partition_key="date",
    ),
    "investment_transactions": PlaidEndpointConfig(
        name="investment_transactions",
        primary_keys=["investment_transaction_id"],
        # Investments at Link only adds the Holdings subscription; the first
        # /investments/transactions/get call adds the separately billed Transactions one.
        should_sync_default=False,
        description="Syncing this table starts Plaid's Investments Transactions subscription for the Item if it does not have one yet.",
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
        partition_key="date",
    ),
    # A holding has no ID of its own: Plaid returns one position per security per account.
    "investment_holdings": PlaidEndpointConfig(
        name="investment_holdings",
        primary_keys=["account_id", "security_id"],
    ),
    "liabilities": PlaidEndpointConfig(
        name="liabilities",
        primary_keys=["account_id"],
    ),
    "institutions": PlaidEndpointConfig(
        name="institutions",
        primary_keys=["institution_id"],
    ),
}

ENDPOINTS = tuple(PLAID_ENDPOINTS.keys())

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in PLAID_ENDPOINTS.items()}

DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in PLAID_ENDPOINTS.items() if config.description
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLAID_ENDPOINTS.items() if config.incremental_fields
}
