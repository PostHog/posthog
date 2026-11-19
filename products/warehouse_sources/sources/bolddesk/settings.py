from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

API_PATH = "/api/v1"

# BoldDesk caps `PerPage` at 100 (default 10).
PER_PAGE = 100

# How an endpoint filters on modification time:
# - "q": the `Q` query param, `lastmodifiedon:{"from":"<UTC>"}` (tickets, contacts, agents, ...).
# - "updated_from_date": the `updatedFromDate` query param (ticket worklogs).
IncrementalFilter = Literal["q", "updated_from_date"]


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=True)
class BoldDeskEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # `OrderBy` value. Every paginated list sorts on its id: BoldDesk paginates by page number, so a
    # sort on a mutable field (the API default is last modified, descending) moves rows that change
    # during a sync across page boundaries and skips or repeats them.
    order_by: Optional[str] = None
    incremental_filter: Optional[IncrementalFilter] = None
    # The response field the server-side filter matches. Empty for full refresh endpoints.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = None
    paginated: bool = True
    extra_params: dict[str, str] = field(default_factory=dict)


BOLDDESK_ENDPOINTS: dict[str, BoldDeskEndpointConfig] = {
    config.name: config
    for config in [
        BoldDeskEndpointConfig(
            name="tickets",
            path="/tickets",
            primary_keys=["ticketId"],
            order_by="ticketId asc",
            incremental_filter="q",
            incremental_fields=[_datetime_field("lastUpdatedOn")],
            partition_key="createdOn",
        ),
        # Replies and notes on every ticket. `Q` filters on the ticket, and a new reply updates its
        # ticket, so a `lastmodifiedon` window returns every reply added since the last sync.
        BoldDeskEndpointConfig(
            name="ticket_updates",
            path="/tickets/updates",
            primary_keys=["ticketUpdateId"],
            order_by="ticketUpdateId asc",
            incremental_filter="q",
            incremental_fields=[_datetime_field("updatedOn")],
            partition_key="createdOn",
        ),
        BoldDeskEndpointConfig(
            name="ticket_worklogs",
            path="/tickets/worklogs",
            primary_keys=["worklogId"],
            order_by="worklogId asc",
            incremental_filter="updated_from_date",
            incremental_fields=[_datetime_field("lastModifiedOn")],
            partition_key="createdOn",
            # A deleted worklog comes back with `isDeleted: true`, so a merge marks it instead of
            # keeping a stale row.
            extra_params={"includeDeletedWorklogs": "true"},
        ),
        BoldDeskEndpointConfig(
            name="contacts",
            path="/contacts",
            primary_keys=["userId"],
            order_by="userId asc",
            incremental_filter="q",
            incremental_fields=[_datetime_field("lastModifiedOn")],
            partition_key="createdOn",
        ),
        BoldDeskEndpointConfig(
            name="contact_groups",
            path="/contact_groups",
            primary_keys=["contactGroupId"],
            order_by="contactGroupId asc",
            incremental_filter="q",
            incremental_fields=[_datetime_field("lastModifiedOn")],
            partition_key="createdOn",
        ),
        BoldDeskEndpointConfig(
            name="agents",
            path="/agents",
            primary_keys=["userId"],
            order_by="userId asc",
            incremental_filter="q",
            incremental_fields=[_datetime_field("lastModifiedOn")],
            partition_key="createdOn",
        ),
        # `lastModifiedOn` is the only sort this endpoint accepts. The response names the field
        # `lastModifiedDate`.
        BoldDeskEndpointConfig(
            name="satisfaction_ratings",
            path="/satisfaction_ratings",
            primary_keys=["surveyResultId"],
            order_by="lastModifiedOn asc",
            incremental_filter="q",
            incremental_fields=[_datetime_field("lastModifiedDate")],
            partition_key="createdOn",
        ),
        BoldDeskEndpointConfig(
            name="groups",
            path="/groups",
            primary_keys=["groupID"],
            order_by="groupId asc",
        ),
        BoldDeskEndpointConfig(
            name="brands",
            path="/brands",
            primary_keys=["brandId"],
            paginated=False,
        ),
    ]
}

ENDPOINTS = tuple(BOLDDESK_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BOLDDESK_ENDPOINTS.items() if config.incremental_fields
}
