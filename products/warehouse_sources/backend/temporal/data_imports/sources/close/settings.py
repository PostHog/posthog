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


# Canonical CRM endpoint set. Incremental support is only enabled where the OpenAPI spec
# exposes a genuine server-side `<field>__gte` filter (see api_inventory.md).
CLOSE_ENDPOINTS: dict[str, CloseEndpointConfig] = {
    "Leads": CloseEndpointConfig(
        name="Leads",
        path="/lead/",
        table_name="leads",
        partition_key="date_created",
    ),
    "Contacts": CloseEndpointConfig(
        name="Contacts",
        path="/contact/",
        table_name="contacts",
        partition_key="date_created",
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
