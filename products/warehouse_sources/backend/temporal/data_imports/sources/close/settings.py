from dataclasses import dataclass, field
from typing import Optional

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
# the offset-paginated ones. Custom fields are appended at runtime from `/custom_field/<type>/`.
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


@dataclass
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
    # Whether the endpoint uses `_skip`/`_limit` offset pagination. A few small dimension
    # endpoints (lead/opportunity statuses, pipelines) return every row in one response and
    # take no pagination params, so they use a single-page paginator instead (see api_inventory.md).
    paginated: bool = True
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
        paginated=False,
    ),
    "OpportunityStatuses": CloseEndpointConfig(
        name="OpportunityStatuses",
        path="/status/opportunity/",
        table_name="opportunity_statuses",
        paginated=False,
    ),
    "Pipelines": CloseEndpointConfig(
        name="Pipelines",
        path="/pipeline/",
        table_name="pipelines",
        paginated=False,
    ),
    "EmailTemplates": CloseEndpointConfig(
        name="EmailTemplates",
        path="/email_template/",
        table_name="email_templates",
    ),
}

ENDPOINTS = tuple(CLOSE_ENDPOINTS.keys())
