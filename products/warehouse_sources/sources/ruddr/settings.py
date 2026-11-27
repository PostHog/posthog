from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class RuddrEndpointConfig:
    name: str
    path: str
    # Ruddr object IDs are globally unique within a workspace, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # The rows carry no member reference, so the endpoint is read once per member with `memberId`
    # and each row gets the member's id as `member_id`.
    member_fanout: bool = False


# Ruddr workspace API list endpoints. Endpoints missing from INCREMENTAL_FIELDS are full refresh only.
RUDDR_ENDPOINTS: dict[str, RuddrEndpointConfig] = {
    "clients": RuddrEndpointConfig(name="clients", path="/clients"),
    "projects": RuddrEndpointConfig(name="projects", path="/projects"),
    "project_tasks": RuddrEndpointConfig(name="project_tasks", path="/project-tasks"),
    "members": RuddrEndpointConfig(name="members", path="/members"),
    "time_entries": RuddrEndpointConfig(name="time_entries", path="/time-entries"),
    "project_prepayments": RuddrEndpointConfig(name="project_prepayments", path="/project-prepayments"),
    "timesheet_attestations": RuddrEndpointConfig(name="timesheet_attestations", path="/timesheet-attestations"),
    "task_categories": RuddrEndpointConfig(name="task_categories", path="/task-categories"),
    "pipeline_activities": RuddrEndpointConfig(name="pipeline_activities", path="/pipeline-activities"),
    "project_roles": RuddrEndpointConfig(name="project_roles", path="/project-roles"),
    "invoices": RuddrEndpointConfig(name="invoices", path="/invoices"),
    "invoice_items": RuddrEndpointConfig(name="invoice_items", path="/invoice-items"),
    "allocations": RuddrEndpointConfig(name="allocations", path="/allocations"),
    "project_members": RuddrEndpointConfig(name="project_members", path="/project-members"),
    "opportunities": RuddrEndpointConfig(name="opportunities", path="/opportunities"),
    "opportunity_stages": RuddrEndpointConfig(name="opportunity_stages", path="/opportunity-stages"),
    "project_health_reports": RuddrEndpointConfig(name="project_health_reports", path="/project-health-reports"),
    "project_expenses": RuddrEndpointConfig(name="project_expenses", path="/project-expenses"),
    "payments": RuddrEndpointConfig(name="payments", path="/payments"),
    "timesheets": RuddrEndpointConfig(name="timesheets", path="/timesheets"),
    "practices": RuddrEndpointConfig(name="practices", path="/practices"),
    "project_revenue_recognition_entries": RuddrEndpointConfig(
        name="project_revenue_recognition_entries", path="/project-revenue-recognition-entries"
    ),
    "credit_notes": RuddrEndpointConfig(name="credit_notes", path="/credit-notes"),
    "companies": RuddrEndpointConfig(name="companies", path="/companies"),
    "cost_periods": RuddrEndpointConfig(name="cost_periods", path="/cost-periods", member_fanout=True),
}

ENDPOINTS = tuple(RUDDR_ENDPOINTS.keys())

# `allocations` also filters on `modifiedAt`, but the field is null on allocations derived from time
# entries and holidays, so a `modifiedAt` filter would never return new derived rows.
_MODIFIED_AT = IncrementalField(
    label="modifiedAt",
    type=IncrementalFieldType.DateTime,
    field="modifiedAt",
    field_type=IncrementalFieldType.DateTime,
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "invoices": [_MODIFIED_AT],
    "credit_notes": [_MODIFIED_AT],
}

# Server-side filter for each incremental field. `OnAfter` is inclusive (`>=`), so a row that shares
# the watermark timestamp is read again and merge dedupes it on `id`.
INCREMENTAL_FILTER_PARAMS: dict[str, str] = {
    "modifiedAt": "modifiedAtOnAfter",
}
