from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class FactorialEndpointConfig:
    name: str
    # Path under the versioned base URL (e.g. "/resources/employees/employees"). Factorial groups
    # resources as `/resources/<group>/<resource>`; the group can move between API versions, so the
    # path is pinned to the version in `factorial.py`.
    path: str
    # Stable created-date field to partition by, or None to skip partitioning. Only set where
    # `created_at` is reliably present on every row — Factorial returns it on transactional records
    # (employees, leaves, shifts, expenses, …) but not on every lookup/config resource.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Static query params sent on every page. Booleans are serialized as the strings Factorial
    # expects, since `requests` would otherwise render Python's `True` as the literal "True".
    params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True


# A focused, canonical HRIS stream set cross-referenced against the Airbyte/Fivetran Factorial
# connectors: people & org structure, contracts, time off, attendance, expenses, payroll, project
# time tracking, and recruiting (ATS). Every list resource is keyed by a unique `id`.
FACTORIAL_ENDPOINTS: dict[str, FactorialEndpointConfig] = {
    "employees": FactorialEndpointConfig(
        name="employees",
        path="/resources/employees/employees",
        partition_key="created_at",
    ),
    "teams": FactorialEndpointConfig(
        name="teams",
        path="/resources/teams/teams",
    ),
    "team_memberships": FactorialEndpointConfig(
        name="team_memberships",
        path="/resources/teams/memberships",
    ),
    "locations": FactorialEndpointConfig(
        name="locations",
        path="/resources/locations/locations",
    ),
    "legal_entities": FactorialEndpointConfig(
        name="legal_entities",
        path="/resources/companies/legal_entities",
    ),
    "contract_versions": FactorialEndpointConfig(
        name="contract_versions",
        path="/resources/contracts/contract_versions",
        partition_key="created_at",
    ),
    "compensations": FactorialEndpointConfig(
        name="compensations",
        path="/resources/contracts/compensations",
    ),
    "leaves": FactorialEndpointConfig(
        name="leaves",
        path="/resources/timeoff/leaves",
        partition_key="created_at",
    ),
    "leave_types": FactorialEndpointConfig(
        name="leave_types",
        path="/resources/timeoff/leave_types",
    ),
    "allowances": FactorialEndpointConfig(
        name="allowances",
        path="/resources/timeoff/allowances",
    ),
    "allowance_stats": FactorialEndpointConfig(
        name="allowance_stats",
        path="/resources/timeoff/allowance_stats",
    ),
    "attendance_shifts": FactorialEndpointConfig(
        name="attendance_shifts",
        path="/resources/attendance/shifts",
        partition_key="created_at",
    ),
    "worked_times": FactorialEndpointConfig(
        name="worked_times",
        path="/resources/attendance/worked_times",
        # Both flags are required by the endpoint. Excluding non-attendable employees keeps the
        # table to people Factorial actually tracks attendance for, instead of emitting an
        # all-zero row per employee per day for everyone else.
        params={"include_time_range_category": "false", "include_non_attendable_employees": "false"},
    ),
    "expenses": FactorialEndpointConfig(
        name="expenses",
        path="/resources/expenses/expenses",
        partition_key="created_at",
    ),
    "payroll_supplements": FactorialEndpointConfig(
        name="payroll_supplements",
        path="/resources/payroll/supplements",
        partition_key="created_at",
    ),
    "flexible_time_records": FactorialEndpointConfig(
        name="flexible_time_records",
        path="/resources/project_management/flexible_time_records",
        partition_key="created_at",
    ),
    "time_records": FactorialEndpointConfig(
        name="time_records",
        path="/resources/project_management/time_records",
    ),
    "projects": FactorialEndpointConfig(
        name="projects",
        path="/resources/project_management/projects",
    ),
    "candidates": FactorialEndpointConfig(
        name="candidates",
        path="/resources/ats/candidates",
        partition_key="created_at",
    ),
    "job_postings": FactorialEndpointConfig(
        name="job_postings",
        path="/resources/ats/job_postings",
    ),
    "applications": FactorialEndpointConfig(
        name="applications",
        path="/resources/ats/applications",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(FACTORIAL_ENDPOINTS.keys())

# Full refresh only. Factorial documents a server-side `updated_after` filter on only a few of the
# endpoints we sync — `project_management/flexible_time_records`, `project_management/time_records`
# and `project_management/subprojects` — and not on the higher-value people/time-off/attendance
# streams (Airbyte's connector confirms this: it filters `updated_at` client-side everywhere except
# `shifts`). Per the implementing-warehouse-sources guidance, a "client-side cursor" that still walks
# every page is not incremental, so we ship every endpoint as full refresh. `time_records` cannot be
# incremental at all: its response carries no `updated_at` column, so there is no cursor for the
# pipeline to advance the watermark on. `flexible_time_records` / `subprojects` could be promoted
# after curl-verifying (with a future-date cutoff) that the filter actually narrows results against a
# live account — which requires a Factorial API key we don't have here.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
