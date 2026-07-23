from dataclasses import dataclass, field
from typing import Optional

HOORAYHR_BASE_URL = "https://api.hoorayhr.io"


@dataclass
class HoorayHREndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """Path relative to the API root (e.g. ``/time-off``)."""
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    """Stable creation-time field used for Delta partitioning; None leaves the table unpartitioned."""


# HoorayHR's public API (OpenAPI spec at https://api.hoorayhr.io/swagger.json) exposes no pagination,
# no cursors, and no server-side timestamp filters on any of these list endpoints — each returns the
# full collection as one bare JSON array, so every table is full refresh only (matching the Airbyte
# connector's capabilities). Report-style endpoints that require date-range parameters
# (/attendance-report, /working-today, /public-holidays) are point-in-time views, not warehouse
# tables, and are deliberately not synced.
HOORAYHR_ENDPOINTS: dict[str, HoorayHREndpointConfig] = {
    "users": HoorayHREndpointConfig(name="users", path="/users", partition_key="createdAt"),
    "time_off": HoorayHREndpointConfig(name="time_off", path="/time-off", partition_key="createdAt"),
    "leave_types": HoorayHREndpointConfig(name="leave_types", path="/leave-types", partition_key="createdAt"),
    "contracts": HoorayHREndpointConfig(name="contracts", path="/contracts", partition_key="createdAt"),
    "sick_leave_dossiers": HoorayHREndpointConfig(
        name="sick_leave_dossiers", path="/sick-leave-dossiers", partition_key="createdAt"
    ),
    "sick_leave_phases": HoorayHREndpointConfig(
        name="sick_leave_phases", path="/sick-leave-phases", partition_key="createdAt"
    ),
    "time_tracking": HoorayHREndpointConfig(name="time_tracking", path="/time-tracking", partition_key="createdAt"),
    "availability": HoorayHREndpointConfig(name="availability", path="/availability", partition_key="createdAt"),
    "entities": HoorayHREndpointConfig(name="entities", path="/entities", partition_key="createdAt"),
    "labels": HoorayHREndpointConfig(name="labels", path="/labels", partition_key="createdAt"),
    "employment_terms": HoorayHREndpointConfig(
        name="employment_terms", path="/employment-terms", partition_key="createdAt"
    ),
    "employment_term_assignments": HoorayHREndpointConfig(
        name="employment_term_assignments", path="/employment-term-assignments", partition_key="createdAt"
    ),
    "document_categories": HoorayHREndpointConfig(
        name="document_categories", path="/document-categories", partition_key="createdAt"
    ),
    "work_location_categories": HoorayHREndpointConfig(
        name="work_location_categories", path="/work-location-categories", partition_key="createdAt"
    ),
    # Rows are teams (with member/leader user-id arrays), keyed by teamId; no timestamps exposed.
    "teams_information": HoorayHREndpointConfig(
        name="teams_information", path="/teams-information", primary_keys=["teamId"]
    ),
}

ENDPOINTS = tuple(HOORAYHR_ENDPOINTS.keys())
