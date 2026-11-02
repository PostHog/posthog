from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Insightly objects share a common audit-field schema: DATE_CREATED_UTC is stamped once at
# creation (stable — safe to partition on) and DATE_UPDATED_UTC advances on every edit (the
# incremental cursor, mapped to the `updated_after_utc` list filter).
DATE_CREATED = "DATE_CREATED_UTC"
DATE_UPDATED = "DATE_UPDATED_UTC"


def _updated_at_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": DATE_UPDATED,
            "type": IncrementalFieldType.DateTime,
            "field": DATE_UPDATED,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen
class InsightlyEndpointConfig:
    name: str
    path: str
    primary_key: str | tuple[str, ...]
    # Only set for endpoints where Insightly exposes the server-side `updated_after_utc` list
    # filter; those endpoints advertise DATE_UPDATED_UTC as the incremental cursor.
    supports_incremental: bool = False
    # Stable creation timestamp used for datetime partitioning. `None` for endpoints (e.g.
    # Pipelines) whose rows carry no creation timestamp.
    partition_key: Optional[str] = DATE_CREATED
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Set when the plain list endpoint takes no `updated_after_utc` and only its `/Search` variant
    # filters server-side; incremental syncs page through this path instead.
    incremental_path: Optional[str] = None
    # Set for per-record sub-resources: `path` carries an `{id}` placeholder that is filled from
    # `parent_id_field` on each row of the `fanout_parent` endpoint.
    fanout_parent: Optional[str] = None
    parent_id_field: Optional[str] = None
    params: dict[str, str] = field(default_factory=dict)

    @property
    def primary_keys(self) -> list[str]:
        return [self.primary_key] if isinstance(self.primary_key, str) else list(self.primary_key)

    @property
    def probe_path(self) -> str:
        """A path that can be requested as-is to check the key's access to this endpoint."""
        if self.fanout_parent is not None:
            return INSIGHTLY_ENDPOINTS[self.fanout_parent].path
        return self.path


def _incremental_endpoint(
    name: str, path: str, primary_key: str, incremental_path: Optional[str] = None
) -> InsightlyEndpointConfig:
    return InsightlyEndpointConfig(
        name=name,
        path=path,
        primary_key=primary_key,
        supports_incremental=True,
        partition_key=DATE_CREATED,
        incremental_fields=_updated_at_incremental_fields(),
        incremental_path=incremental_path,
    )


INSIGHTLY_ENDPOINTS: dict[str, InsightlyEndpointConfig] = {
    "Contacts": _incremental_endpoint("Contacts", "/Contacts", "CONTACT_ID"),
    "Organisations": _incremental_endpoint("Organisations", "/Organisations", "ORGANISATION_ID"),
    "Opportunities": _incremental_endpoint("Opportunities", "/Opportunities", "OPPORTUNITY_ID"),
    "Leads": _incremental_endpoint("Leads", "/Leads", "LEAD_ID"),
    "Projects": _incremental_endpoint("Projects", "/Projects", "PROJECT_ID"),
    "Tasks": _incremental_endpoint("Tasks", "/Tasks", "TASK_ID"),
    "Events": _incremental_endpoint("Events", "/Events", "EVENT_ID"),
    "Notes": _incremental_endpoint("Notes", "/Notes", "NOTE_ID"),
    "Emails": _incremental_endpoint("Emails", "/Emails", "EMAIL_ID"),
    # Users list is a small, admin-scoped metadata table with no `updated_after_utc` filter, so
    # it's full refresh only. It still carries DATE_CREATED_UTC for partitioning.
    "Users": InsightlyEndpointConfig(name="Users", path="/Users", primary_key="USER_ID"),
    # Pipelines / stages are configuration objects without audit timestamps: full refresh, no
    # partitioning.
    "Pipelines": InsightlyEndpointConfig(
        name="Pipelines", path="/Pipelines", primary_key="PIPELINE_ID", partition_key=None
    ),
    "PipelineStages": InsightlyEndpointConfig(
        name="PipelineStages", path="/PipelineStages", primary_key="STAGE_ID", partition_key=None
    ),
    "LeadSources": InsightlyEndpointConfig(
        name="LeadSources", path="/LeadSources", primary_key="LEAD_SOURCE_ID", partition_key=None
    ),
    "LeadStatuses": InsightlyEndpointConfig(
        name="LeadStatuses",
        path="/LeadStatuses",
        primary_key="LEAD_STATUS_ID",
        partition_key=None,
        # The converted status is left out by default, but converted leads still reference it.
        params={"include_converted": "true"},
    ),
    "OpportunityLineItem": _incremental_endpoint(
        "OpportunityLineItem",
        "/OpportunityLineItem",
        "OPPORTUNITY_ITEM_ID",
        incremental_path="/OpportunityLineItem/Search",
    ),
    "Ticket": _incremental_endpoint("Ticket", "/Ticket", "TICKET_ID", incremental_path="/Ticket/Search"),
    "Quotation": _incremental_endpoint("Quotation", "/Quotation", "QUOTE_ID", incremental_path="/Quotation/Search"),
    "QuotationLineItem": _incremental_endpoint(
        "QuotationLineItem",
        "/QuotationLineItem",
        "QUOTATION_ITEM_ID",
        incremental_path="/QuotationLineItem/Search",
    ),
    "Product": _incremental_endpoint("Product", "/Product", "PRODUCT_ID", incremental_path="/Product/Search"),
    "Pricebook": _incremental_endpoint("Pricebook", "/Pricebook", "PRICEBOOK_ID", incremental_path="/Pricebook/Search"),
    "PricebookEntry": _incremental_endpoint(
        "PricebookEntry",
        "/PricebookEntry",
        "PRICEBOOK_ENTRY_ID",
        incremental_path="/PricebookEntry/Search",
    ),
    # One request per opportunity and no server-side filter, so full refresh only. History rows
    # carry no id of their own; a transition is identified by its opportunity, time, and state.
    "OpportunityStateHistory": InsightlyEndpointConfig(
        name="OpportunityStateHistory",
        path="/Opportunities/{id}/StateHistory",
        primary_key=("OPPORTUNITY_ID", "DATE_CHANGED_UTC", "FOR_OPPORTUNITY_STATE"),
        partition_key="DATE_CHANGED_UTC",
        fanout_parent="Opportunities",
        parent_id_field="OPPORTUNITY_ID",
    ),
}

ENDPOINTS = tuple(INSIGHTLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INSIGHTLY_ENDPOINTS.items()
}
