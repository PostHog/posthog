from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _date_incremental_field(name: str) -> IncrementalField:
    # Close timestamps are ISO 8601 strings (e.g. "2024-01-01T00:00:00+00:00").
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Standard fields returned by the plain list endpoints. Advanced Filtering only returns the
# fields you name, so these lists are what keeps the search-backed tables column-compatible with
# the offset-paginated ones. A single `custom` selector for every custom field is added at
# runtime (see ALL_CUSTOM_FIELDS_SELECTOR).
LEAD_SEARCH_FIELDS = [
    "addresses",
    "contact_ids",
    "contacts",
    "created_by",
    "created_by_name",
    "date_created",
    "date_updated",
    "description",
    "display_name",
    "html_url",
    "id",
    "integration_links",
    "name",
    "opportunities",
    "organization_id",
    "status_id",
    "status_label",
    "tasks",
    "updated_by",
    "updated_by_name",
    "url",
]

CONTACT_SEARCH_FIELDS = [
    "created_by",
    "date_created",
    "date_updated",
    "display_name",
    "emails",
    "id",
    "integration_links",
    "lead_id",
    "name",
    "organization_id",
    "phones",
    "title",
    "updated_by",
    "urls",
]


# How an endpoint pages. "offset" is Close's usual `_skip`/`_limit`. A few small dimension
# endpoints (lead/opportunity statuses, pipelines, shared custom fields) return every row in one
# response and take no pagination params ("single_page"). The event log rejects `_skip` entirely
# and pages with `_cursor`/`cursor_next` ("event_cursor"). See api_inventory.md.
PaginationStyle = Literal["offset", "single_page", "event_cursor"]


@frozen
class CloseEndpointConfig:
    name: str
    path: str
    table_name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    data_selector: str = "data"
    # Advertised incremental cursor options. Empty => full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field used for datetime partitioning. None => no partitioning.
    partition_key: Optional[str] = None
    # Whether the list endpoint accepts the `_order_by` query param (needed to force
    # ascending order for incremental cursor advancement).
    supports_order_by: bool = False
    pagination: PaginationStyle = "offset"
    # Order rows arrive in. Only the event log is descending, and it offers no sort param.
    sort_mode: SortMode = "asc"
    # `/organization/{id}/` has no list counterpart, so the organization ids come from `/me/`
    # and each organization is fetched on its own (see close.py).
    fan_out_from_me: bool = False
    # Advanced Filtering object type. Set only for the two resources whose list endpoints expose
    # no date filter at all, so offset pagination is the only option and Close's `_skip` cap
    # eventually truncates the table (see api_inventory.md).
    search_object_type: Optional[str] = None
    # Fields to request from Advanced Filtering. Required when `search_object_type` is set.
    search_fields: list[str] = field(default_factory=list)


# Canonical CRM endpoint set. Incremental support is only enabled where a genuine server-side
# date filter exists — a `<field>__gte` query param on the list endpoint, or a `moment_range`
# condition on Advanced Filtering for the two resources routed there (see api_inventory.md).
CLOSE_ENDPOINTS: dict[str, CloseEndpointConfig] = {
    "Leads": CloseEndpointConfig(
        name="Leads",
        path="/lead/",
        table_name="leads",
        incremental_fields=[_date_incremental_field("date_created"), _date_incremental_field("date_updated")],
        partition_key="date_created",
        search_object_type="lead",
        search_fields=LEAD_SEARCH_FIELDS,
    ),
    "Contacts": CloseEndpointConfig(
        name="Contacts",
        path="/contact/",
        table_name="contacts",
        incremental_fields=[_date_incremental_field("date_created"), _date_incremental_field("date_updated")],
        partition_key="date_created",
        search_object_type="contact",
        search_fields=CONTACT_SEARCH_FIELDS,
    ),
    "Opportunities": CloseEndpointConfig(
        name="Opportunities",
        path="/opportunity/",
        table_name="opportunities",
        incremental_fields=[_date_incremental_field("date_created"), _date_incremental_field("date_updated")],
        partition_key="date_created",
        supports_order_by=True,
    ),
    "Activities": CloseEndpointConfig(
        name="Activities",
        path="/activity/",
        table_name="activities",
        incremental_fields=[_date_incremental_field("date_created")],
        partition_key="date_created",
        supports_order_by=True,
    ),
    "Tasks": CloseEndpointConfig(
        name="Tasks",
        path="/task/",
        table_name="tasks",
        incremental_fields=[_date_incremental_field("date_created"), _date_incremental_field("date_updated")],
        partition_key="date_created",
        supports_order_by=True,
    ),
    "Users": CloseEndpointConfig(
        name="Users",
        path="/user/",
        table_name="users",
    ),
    "LeadStatuses": CloseEndpointConfig(
        name="LeadStatuses",
        path="/status/lead/",
        table_name="lead_statuses",
        pagination="single_page",
    ),
    "OpportunityStatuses": CloseEndpointConfig(
        name="OpportunityStatuses",
        path="/status/opportunity/",
        table_name="opportunity_statuses",
        pagination="single_page",
    ),
    "Pipelines": CloseEndpointConfig(
        name="Pipelines",
        path="/pipeline/",
        table_name="pipelines",
        pagination="single_page",
    ),
    "EmailTemplates": CloseEndpointConfig(
        name="EmailTemplates",
        path="/email_template/",
        table_name="email_templates",
    ),
    "Events": CloseEndpointConfig(
        name="Events",
        path="/event/",
        table_name="events",
        incremental_fields=[_date_incremental_field("date_updated")],
        partition_key="date_created",
        pagination="event_cursor",
        sort_mode="desc",
    ),
    "Outcomes": CloseEndpointConfig(
        name="Outcomes",
        path="/outcome/",
        table_name="outcomes",
    ),
    "Organizations": CloseEndpointConfig(
        name="Organizations",
        path="/organization/{id}/",
        table_name="organizations",
        pagination="single_page",
        fan_out_from_me=True,
    ),
    "LeadCustomFields": CloseEndpointConfig(
        name="LeadCustomFields",
        path="/custom_field/lead/",
        table_name="lead_custom_fields",
    ),
    "ContactCustomFields": CloseEndpointConfig(
        name="ContactCustomFields",
        path="/custom_field/contact/",
        table_name="contact_custom_fields",
    ),
    "OpportunityCustomFields": CloseEndpointConfig(
        name="OpportunityCustomFields",
        path="/custom_field/opportunity/",
        table_name="opportunity_custom_fields",
    ),
    "ActivityCustomFields": CloseEndpointConfig(
        name="ActivityCustomFields",
        path="/custom_field/activity/",
        table_name="activity_custom_fields",
    ),
    "SharedCustomFields": CloseEndpointConfig(
        name="SharedCustomFields",
        path="/custom_field/shared/",
        table_name="shared_custom_fields",
        pagination="single_page",
    ),
}

ENDPOINTS = tuple(CLOSE_ENDPOINTS.keys())
