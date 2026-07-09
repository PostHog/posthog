from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ChartHopEndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """API path relative to the base URL, with ``{org_id}`` left for the resolved org."""
    primary_key: list[str] = field(default_factory=lambda: ["id"])
    extra_params: dict[str, Any] = field(default_factory=dict)
    """Static query params sent on every request for the endpoint."""
    incremental_param: Optional[str] = None
    """Server-side "start from" query param. Only set where the API genuinely filters."""
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = None
    """A STABLE field to partition on. Never an updated_at-style field, which would
    rewrite partitions on every sync."""


# Every ChartHop list endpoint paginates the same way: cursor-by-id via ``from=<last id>``
# plus ``limit=<n>``, with the response envelope ``{"data": [...], "next": "<from token>"}``.
#
# Incremental sync is only advertised on ``changes``: /v1/org/{orgId}/change accepts a
# server-side ``date`` (start, inclusive) filter on the change's effective date and returns
# rows in ascending date order by default (``desc=false``). Person, job, and group list
# endpoints support as-of ``date`` snapshots but no updated-since filter, and the time-off
# endpoint's ``fromDate`` filters on the time off's own date range (backdated requests
# entered later would be skipped forever), so all of those are full refresh only.
CHARTHOP_ENDPOINTS: dict[str, ChartHopEndpointConfig] = {
    "persons": ChartHopEndpointConfig(
        name="persons",
        path="/v2/org/{org_id}/person",
        # Include ex-employees so departures stay queryable in the warehouse.
        extra_params={"includeAll": "true"},
    ),
    "jobs": ChartHopEndpointConfig(
        name="jobs",
        path="/v2/org/{org_id}/job",
    ),
    "groups": ChartHopEndpointConfig(
        name="groups",
        path="/v2/org/{org_id}/group",
    ),
    "group_types": ChartHopEndpointConfig(
        name="group_types",
        path="/v1/org/{org_id}/group-type",
    ),
    "job_levels": ChartHopEndpointConfig(
        name="job_levels",
        path="/v1/org/{org_id}/job-level",
    ),
    "job_codes": ChartHopEndpointConfig(
        name="job_codes",
        path="/v1/org/{org_id}/job-code",
    ),
    "changes": ChartHopEndpointConfig(
        name="changes",
        path="/v1/org/{org_id}/change",
        incremental_param="date",
        # A change's effective date is set once and rarely edited, so it doubles as a
        # stable partition key (createAt isn't guaranteed present on older rows).
        partition_key="date",
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "time_off": ChartHopEndpointConfig(
        name="time_off",
        path="/v1/org/{org_id}/timeoff",
    ),
}

ENDPOINTS = tuple(CHARTHOP_ENDPOINTS.keys())
