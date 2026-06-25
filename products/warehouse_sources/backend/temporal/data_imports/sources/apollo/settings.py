from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_UPDATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class ApolloEndpointConfig:
    name: str
    # Search path under /api/v1 (search endpoints are POSTs with JSON bodies).
    path: str
    # Key the rows live under in the response body.
    data_key: str
    primary_key: str = "id"
    # Apollo has no server-side timestamp filter; incremental streams sort
    # descending on this field and stop at the persisted high-water mark
    # (the same CDC emulation Fivetran uses on CONTACT/ACCOUNT).
    sort_by_field: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = None


APOLLO_ENDPOINTS: dict[str, ApolloEndpointConfig] = {
    "contacts": ApolloEndpointConfig(
        name="contacts",
        path="/contacts/search",
        data_key="contacts",
        sort_by_field="contact_updated_at",
        partition_key="created_at",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
    ),
    "accounts": ApolloEndpointConfig(
        name="accounts",
        path="/accounts/search",
        data_key="accounts",
        sort_by_field="account_updated_at",
        partition_key="created_at",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
    ),
    "opportunities": ApolloEndpointConfig(
        name="opportunities",
        path="/opportunities/search",
        data_key="opportunities",
    ),
}

ENDPOINTS = tuple(APOLLO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APOLLO_ENDPOINTS.items() if config.incremental_fields
}
