from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class RuddrEndpointConfig:
    name: str
    path: str
    # Ruddr object IDs are globally unique within a workspace, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


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
}

ENDPOINTS = tuple(RUDDR_ENDPOINTS.keys())

# `allocations` also filters on `modifiedAt`, but the field is null on allocations derived from time
# entries and holidays, so a `modifiedAt` filter would never return new derived rows.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "invoices": [
        IncrementalField(
            label="modifiedAt",
            type=IncrementalFieldType.DateTime,
            field="modifiedAt",
            field_type=IncrementalFieldType.DateTime,
        )
    ],
}

# Server-side filter for each incremental field. `OnAfter` is inclusive (`>=`), so a row that shares
# the watermark timestamp is read again and merge dedupes it on `id`.
INCREMENTAL_FILTER_PARAMS: dict[str, str] = {
    "modifiedAt": "modifiedAtOnAfter",
}
