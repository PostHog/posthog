from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_UPDATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@frozen
class ApolloEndpointConfig:
    name: str
    # Path under /api/v1 (search endpoints are POSTs with JSON bodies, lookups are GETs).
    path: str
    # Key the rows live under in the response body.
    data_key: str
    primary_key: str = "id"
    method: str = "POST"
    # The stage lookups return their whole set in one response, with no page params
    # and no pagination object to walk.
    paginated: bool = True
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
    "users": ApolloEndpointConfig(
        name="users",
        path="/users/search",
        data_key="users",
        method="GET",
    ),
    "contact_stages": ApolloEndpointConfig(
        name="contact_stages",
        path="/contact_stages",
        data_key="contact_stages",
        method="GET",
        paginated=False,
    ),
    "account_stages": ApolloEndpointConfig(
        name="account_stages",
        path="/account_stages",
        data_key="account_stages",
        method="GET",
        paginated=False,
    ),
    "opportunity_stages": ApolloEndpointConfig(
        name="opportunity_stages",
        path="/opportunity_stages",
        data_key="opportunity_stages",
        method="GET",
        paginated=False,
    ),
}

ENDPOINTS = tuple(APOLLO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APOLLO_ENDPOINTS.items() if config.incremental_fields
}
