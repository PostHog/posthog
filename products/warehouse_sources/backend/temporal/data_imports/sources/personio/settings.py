from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The compensations listing only answers for one calendar month at a time, so a sync walks month
# windows. This bounds how far back the walk starts when there is no watermark yet.
COMPENSATIONS_LOOKBACK_MONTHS = 24

_UPDATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class PersonioEndpointConfig:
    name: str
    path: str
    # OAuth scope the endpoint needs (surfaced in the source caption).
    scope: str
    primary_keys: tuple[str, ...] = ("id",)
    # Server-side updated_at filter param. Personio v2 is inconsistent per
    # endpoint: persons use strict `.gt`, the period endpoints use `.gte`.
    incremental_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Max page size the endpoint accepts (persons cap at 50, periods at 100). None for
    # unpaginated endpoints, which then get no `limit` param.
    page_size: Optional[int] = 100
    # Stable creation-time field used for datetime partitioning.
    partition_key: Optional[str] = None
    # Child endpoints listed once per parent row (e.g. employments per person).
    fanout: Optional[DependentEndpointConfig] = None
    default_incremental_field: Optional[str] = None
    # Endpoints with a required filter are listed once per variant (e.g. org units per type).
    query_variants: tuple[dict[str, str], ...] = ()
    # Walk calendar-month start_date/end_date windows (compensations).
    monthly_windows: bool = False


PERSONIO_ENDPOINTS: dict[str, PersonioEndpointConfig] = {
    "persons": PersonioEndpointConfig(
        name="persons",
        path="/v2/persons",
        scope="personio:persons:read",
        incremental_param="updated_at.gt",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
        page_size=50,
        partition_key="created_at",
    ),
    # Employment ids are only documented per person, so the key carries the person id too. The
    # listing is per person and newest-first, so incremental runs merge without an ordered cursor.
    "employments": PersonioEndpointConfig(
        name="employments",
        path="/v2/persons/{person_id}/employments",
        scope="personio:persons:read",
        primary_keys=("person_id", "id"),
        incremental_param="updated_at.gt",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
        page_size=50,
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="persons",
            resolve_param="person_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "person_id"},
        ),
    ),
    # One row per compensation per month window: recurring compensations repeat in every window,
    # so the window start is part of the key. Full refresh only: a compensation can be added to a
    # past month at any time, and the API has no change timestamp to find it with.
    "compensations": PersonioEndpointConfig(
        name="compensations",
        path="/v2/compensations",
        scope="personio:compensations:read",
        primary_keys=("period_start", "id"),
        monthly_windows=True,
    ),
    "absence_periods": PersonioEndpointConfig(
        name="absence_periods",
        path="/v2/absence-periods",
        scope="personio:absences:read",
        incremental_param="updated_at.gte",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
    ),
    "attendance_periods": PersonioEndpointConfig(
        name="attendance_periods",
        path="/v2/attendance-periods",
        scope="personio:attendances:read",
        incremental_param="updated_at.gte",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
    ),
    # Salary bands and cost centers are dimension lookups: no updated_at/created_at field, so no
    # server-side timestamp filter and no partition key — full refresh only.
    "salary_bands": PersonioEndpointConfig(
        name="salary_bands",
        path="/v2/salary-bands",
        scope="personio:salary-bands:read",
    ),
    "cost_centers": PersonioEndpointConfig(
        name="cost_centers",
        path="/v2/cost-centers",
        scope="personio:cost-centers:read",
    ),
    # Absence types and org units are lookups with no server-side timestamp filter — full refresh only.
    "absence_types": PersonioEndpointConfig(
        name="absence_types",
        path="/v2/absence-types",
        scope="personio:absences:read",
    ),
    # `type` is a required filter, so departments and teams are two listings in one table.
    "org_units": PersonioEndpointConfig(
        name="org_units",
        path="/v2/org-units",
        scope="personio:org-units:read",
        primary_keys=("type", "id"),
        query_variants=(
            {"type": "department", "include_parent_chain": "true"},
            {"type": "team", "include_parent_chain": "true"},
        ),
    ),
    # Recruiting jobs support `updated_at.gt`, but their updated_at/created_at are
    # {"date-time", "timezone"} objects that can't serve as a cursor or partition column, and the
    # listing is newest-first — so full refresh only.
    "recruiting_jobs": PersonioEndpointConfig(
        name="recruiting_jobs",
        path="/v2/recruiting/jobs",
        scope="personio:recruiting:read",
        page_size=200,
    ),
    "recruiting_categories": PersonioEndpointConfig(
        name="recruiting_categories",
        path="/v2/recruiting/categories",
        scope="personio:recruiting:read",
        page_size=None,
    ),
}

ENDPOINTS = tuple(PERSONIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PERSONIO_ENDPOINTS.items() if config.incremental_fields
}
