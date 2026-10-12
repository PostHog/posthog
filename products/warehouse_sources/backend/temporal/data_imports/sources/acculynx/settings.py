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
}

# ModifiedDate filtering needs account-level verification before incremental sync can be enabled.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
