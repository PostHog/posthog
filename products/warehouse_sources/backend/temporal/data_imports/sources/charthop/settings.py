from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Vendor API versions this source implements, as opaque labels (never parsed or ordered).
# ``v1`` is the legacy pin (the base-class `UNVERSIONED_API_VERSION`); ``v2`` adopts ChartHop's
# v2 ``change`` resource. Only the ``changes`` endpoint's request differs between the two — every
# other resource is served under a single path ChartHop offers, identical for both pins.
CHARTHOP_V1 = "v1"
CHARTHOP_V2 = "v2"
SUPPORTED_VERSIONS = (CHARTHOP_V1, CHARTHOP_V2)
DEFAULT_VERSION = CHARTHOP_V2


@dataclass
class ChartHopEndpointVersionOverride:
    """Per-version request differences for a resource ChartHop serves under more than one API
    version. Unset fields fall through to the endpoint's base (v1) values."""

    path: Optional[str] = None
    incremental_param: Optional[str] = None


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
    version_overrides: dict[str, ChartHopEndpointVersionOverride] = field(default_factory=dict)
    """Resolved-``api_version`` → request overrides. Absent versions use the base (v1) request."""


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
        # v2 serves the change list at /v2/org/{orgId}/change and renames the start-date
        # filter param from ``date`` to ``fromDate``; the envelope, cursor, and row fields
        # (including the ``date`` field this partitions/increments on) are unchanged.
        version_overrides={
            CHARTHOP_V2: ChartHopEndpointVersionOverride(
                path="/v2/org/{org_id}/change",
                incremental_param="fromDate",
            ),
        },
    ),
    "time_off": ChartHopEndpointConfig(
        name="time_off",
        path="/v1/org/{org_id}/timeoff",
    ),
}

ENDPOINTS = tuple(CHARTHOP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CHARTHOP_ENDPOINTS.items()
}


def resolve_endpoint_version(config: ChartHopEndpointConfig, api_version: str) -> tuple[str, Optional[str]]:
    """Effective ``(path template, incremental query param)`` for a resolved ``api_version`` pin.

    A version without an override — including an unknown or legacy label honored verbatim by
    ``resolve_api_version`` — falls back to the base (v1) request rather than being dropped.
    """
    override = config.version_overrides.get(api_version)
    if override is None:
        return config.path, config.incremental_param
    return override.path or config.path, override.incremental_param or config.incremental_param
