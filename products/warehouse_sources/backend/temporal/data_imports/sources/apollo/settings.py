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
    # Apollo splits its POST search endpoints: the CRM object searches read page params
    # from the JSON body, the sequence and task searches only from the query string.
    page_params_in_query: bool = False
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
    # The four endpoints below are full refresh only. None of them expose a
    # server-side filter on a creation or modification timestamp, and the fields that
    # do move after the record is written (an email's open/click/reply status, a call's
    # transcription, a task's completion) are exactly the ones a user reads, so a
    # date-windowed sync would freeze them at their first-imported value.
    "emailer_messages": ApolloEndpointConfig(
        name="emailer_messages",
        path="/emailer_messages/search",
        data_key="emailer_messages",
        method="GET",
        partition_key="created_at",
    ),
    "phone_calls": ApolloEndpointConfig(
        name="phone_calls",
        path="/phone_calls/search",
        data_key="phone_calls",
        method="GET",
        # Calls carry no created_at; start_time is when the call was placed and never moves.
        partition_key="start_time",
    ),
    "tasks": ApolloEndpointConfig(
        name="tasks",
        path="/tasks/search",
        data_key="tasks",
        page_params_in_query=True,
        partition_key="created_at",
    ),
    "emailer_campaigns": ApolloEndpointConfig(
        name="emailer_campaigns",
        path="/emailer_campaigns/search",
        data_key="emailer_campaigns",
        page_params_in_query=True,
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
