from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Scopes requested when minting the client-credentials token. Scopes are fixed
# on the developer app at creation, so the caption tells users to grant these.
TOKEN_SCOPES = "transactions:read reimbursements:read users:read cards:read departments:read"


@dataclass
class RampEndpointConfig:
    name: str
    # Path under {host}/developer/v1.
    path: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param that pushes the incremental cursor server-side.
    incremental_param: Optional[str] = None
    # Stable event-time field used for datetime partitioning.
    partition_key: Optional[str] = None


RAMP_ENDPOINTS: dict[str, RampEndpointConfig] = {
    "transactions": RampEndpointConfig(
        name="transactions",
        path="/transactions",
        partition_key="user_transaction_time",
        # from_date filters on the transaction time. There is no updated_after,
        # so late state changes (pending→cleared) need an occasional full
        # refresh — the same trade-off Fivetran makes.
        incremental_param="from_date",
        incremental_fields=[
            {
                "label": "user_transaction_time",
                "type": IncrementalFieldType.DateTime,
                "field": "user_transaction_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "reimbursements": RampEndpointConfig(
        name="reimbursements",
        path="/reimbursements",
    ),
    "users": RampEndpointConfig(
        name="users",
        path="/users",
    ),
    "cards": RampEndpointConfig(
        name="cards",
        path="/cards",
    ),
    "departments": RampEndpointConfig(
        name="departments",
        path="/departments",
    ),
}

ENDPOINTS = tuple(RAMP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RAMP_ENDPOINTS.items() if config.incremental_fields
}
