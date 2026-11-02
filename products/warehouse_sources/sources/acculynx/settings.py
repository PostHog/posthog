from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

API_ORIGIN = "https://api.acculynx.com"
PAGE_SIZE = 25
MAX_JOB_RECORDS = 100_000


@frozen
class AcculynxEndpoint:
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    offset_param: str | None = "recordStartIndex"
    data_selector: str = "items"
    partition_key: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    fanout: DependentEndpointConfig | None = None


ENDPOINTS: dict[str, AcculynxEndpoint] = {
    "jobs": AcculynxEndpoint(
        path="jobs",
        partition_key="createdDate",
        params={"includes": "contact,initialAppointment", "sortBy": "CreatedDate", "sortOrder": "Ascending"},
    ),
    "contacts": AcculynxEndpoint(
        path="contacts",
        offset_param="pageStartIndex",
        partition_key="createdDate",
        params={"includes": "emailAddress,phoneNumber"},
    ),
    "estimates": AcculynxEndpoint(
        path="estimates/{estimateId}",
        offset_param=None,
        data_selector="$",
        primary_keys=("estimate_id", "id"),
        partition_key="createdDate",
        params={"includes": "job,createdBy,modifiedBy,sections"},
        fanout=DependentEndpointConfig(
            parent_name="estimate_index",
            resolve_param="estimateId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "estimate_id"},
        ),
    ),
    "invoices": AcculynxEndpoint(
        path="jobs/{jobId}/invoices",
        offset_param="pageStartIndex",
        primary_keys=("job_id", "id"),
        partition_key="createdDate",
        params={"sortOrder": "Ascending"},
        fanout=DependentEndpointConfig(
            parent_name="jobs",
            resolve_param="jobId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "job_id"},
        ),
    ),
    "financials": AcculynxEndpoint(
        path="jobs/{jobId}/financials",
        offset_param=None,
        data_selector="$",
        primary_keys=("job_id", "id"),
        fanout=DependentEndpointConfig(
            parent_name="jobs",
            resolve_param="jobId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "job_id"},
        ),
    ),
    "payments": AcculynxEndpoint(
        path="jobs/{jobId}/payments",
        offset_param=None,
        data_selector="$",
        primary_keys=("job_id", "payment_category", "id"),
        fanout=DependentEndpointConfig(
            parent_name="jobs",
            resolve_param="jobId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "job_id"},
        ),
    ),
    "job_milestone_history": AcculynxEndpoint(
        path="jobs/{jobId}/milestone-history",
        offset_param=None,
        primary_keys=("job_id", "name", "date"),
        partition_key="date",
        fanout=DependentEndpointConfig(
            parent_name="jobs",
            resolve_param="jobId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "job_id"},
        ),
    ),
    # History rows have no identifier, so every documented field is part of the key.
    "job_history": AcculynxEndpoint(
        path="jobs/{jobId}/history",
        primary_keys=("job_id", "date", "type", "action"),
        partition_key="date",
        fanout=DependentEndpointConfig(
            parent_name="jobs",
            resolve_param="jobId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "job_id"},
        ),
    ),
    "financial_amendments": AcculynxEndpoint(
        path="financials/{financialsId}/amendments",
        offset_param="pageStartIndex",
        primary_keys=("financials_id", "id"),
        partition_key="createdDate",
        fanout=DependentEndpointConfig(
            parent_name="financials",
            resolve_param="financialsId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "financials_id"},
        ),
    ),
    "estimate_section_items": AcculynxEndpoint(
        path="estimates/{estimateId}/sections/{estimateSectionId}/items",
        offset_param=None,
        primary_keys=("estimate_id", "estimate_section_id", "id"),
        fanout=DependentEndpointConfig(
            parent_name="estimate_sections",
            resolve_param="estimateSectionId",
            resolve_field="id",
            include_from_parent=["id", "_estimate_index_id"],
            parent_field_renames={"id": "estimate_section_id", "_estimate_index_id": "estimate_id"},
            child_params={
                "estimateId": {"type": "resolve", "resource": "estimate_sections", "field": "_estimate_index_id"}
            },
        ),
    ),
    "calendars": AcculynxEndpoint(path="calendars"),
    "calendar_appointments": AcculynxEndpoint(
        path="calendars/{calendarId}/appointments",
        primary_keys=("calendar_id", "id"),
        fanout=DependentEndpointConfig(
            parent_name="calendars",
            resolve_param="calendarId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "calendar_id"},
        ),
    ),
    "lead_sources": AcculynxEndpoint(path="company-settings/leads/lead-sources"),
    "users": AcculynxEndpoint(
        path="users",
        offset_param="pageStartIndex",
        params={"status": "Active,Inactive,Archived,Deleted"},
    ),
}

PARENT_ENDPOINTS = {
    **ENDPOINTS,
    "estimate_index": AcculynxEndpoint(path="estimates", offset_param="pageStartIndex"),
    "estimate_sections": AcculynxEndpoint(
        path="estimates/{estimateId}/sections",
        offset_param=None,
        fanout=DependentEndpointConfig(
            parent_name="estimate_index",
            resolve_param="estimateId",
            resolve_field="id",
            include_from_parent=["id"],
        ),
    ),
}

# ModifiedDate filtering needs account-level verification before incremental sync can be enabled.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
