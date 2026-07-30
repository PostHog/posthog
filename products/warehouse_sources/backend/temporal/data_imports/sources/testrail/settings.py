from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Paginated bulk endpoints accept a `limit` of up to 250; the largest page minimises round trips.
PAGE_SIZE = 250

# Where the endpoint sits in TestRail's resource hierarchy, which drives fan-out:
# instance-level endpoints are a single listing, project/suite/run endpoints iterate parents.
TestrailScope = Literal["instance", "project", "suite", "run"]


def _epoch_incremental_field(name: str) -> list[IncrementalField]:
    # TestRail timestamps (`created_on` / `updated_on`) are UNIX epoch integers, and its
    # `*_after` filters take the same epoch format, so the advertised cursor is an Integer.
    return [
        {
            "label": name,
            "type": IncrementalFieldType.Integer,
            "field": name,
            "field_type": IncrementalFieldType.Integer,
        },
    ]


@dataclass
class TestrailEndpointConfig:
    name: str
    # API method segment, e.g. "get_cases" in index.php?/api/v2/get_cases/{project_id}.
    method: str
    scope: TestrailScope
    # Key of the record list inside the bulk pagination envelope
    # ({"offset": ..., "limit": ..., "size": ..., "_links": ..., "<key>": [...]}). Endpoints
    # documented as returning a plain JSON array still declare it so the transport tolerates
    # either shape.
    response_key: str
    # Whether the endpoint documents limit/offset pagination (TestRail 6.7+ bulk endpoints).
    paginated: bool
    # Server-side UNIX-timestamp filter param (e.g. "updated_after"); None = full refresh only.
    incremental_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # TestRail record IDs are instance-global (case C123 / run R45 identifiers are unique across
    # projects), so `id` is a safe table-wide primary key even for fan-out endpoints.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable UNIX-timestamp field to bucket the Delta table on (datetime partitioning). Never the
    # incremental cursor when that is `updated_after` — a partition key must not move, so `cases`
    # partitions on `created_on` even though it syncs incrementally on `updated_on`. Only set for
    # endpoints whose records carry `created_on`; the rest stay unpartitioned.
    partition_key: Optional[str] = None


TESTRAIL_ENDPOINTS: dict[str, TestrailEndpointConfig] = {
    "projects": TestrailEndpointConfig(
        name="projects",
        method="get_projects",
        scope="instance",
        response_key="projects",
        # get_projects only filters by is_completed — no server-side timestamp, so full refresh.
        paginated=True,
    ),
    "users": TestrailEndpointConfig(
        name="users",
        method="get_users",
        scope="project",
        response_key="users",
        # Documented as a plain array; instance-wide listing needs an administrator account, so
        # the transport falls back to per-project listing (see _users_rows).
        paginated=False,
    ),
    "suites": TestrailEndpointConfig(
        name="suites",
        method="get_suites",
        scope="project",
        response_key="suites",
        paginated=False,
    ),
    "sections": TestrailEndpointConfig(
        name="sections",
        method="get_sections",
        scope="suite",
        response_key="sections",
        # get_sections exposes no timestamp filter, so full refresh only.
        paginated=True,
    ),
    "cases": TestrailEndpointConfig(
        name="cases",
        method="get_cases",
        scope="suite",
        response_key="cases",
        paginated=True,
        # get_cases filters server-side on updated_after (UNIX timestamp against updated_on).
        incremental_param="updated_after",
        incremental_fields=_epoch_incremental_field("updated_on"),
        partition_key="created_on",
    ),
    "milestones": TestrailEndpointConfig(
        name="milestones",
        method="get_milestones",
        scope="project",
        response_key="milestones",
        # Only is_completed / is_started filters are documented — no timestamp, full refresh.
        paginated=True,
    ),
    "runs": TestrailEndpointConfig(
        name="runs",
        method="get_runs",
        scope="project",
        response_key="runs",
        paginated=True,
        # get_runs / get_plans filter on created_after only (runs have no updated_after filter),
        # so incremental catches new runs but not later edits — completion state on already
        # synced rows only refreshes on a full refresh. Plan-entry runs ride the plan's
        # created_after, so runs added to a pre-watermark plan are also full-refresh-only
        # (see _runs_rows).
        incremental_param="created_after",
        incremental_fields=_epoch_incremental_field("created_on"),
        partition_key="created_on",
    ),
    "plans": TestrailEndpointConfig(
        name="plans",
        method="get_plans",
        scope="project",
        response_key="plans",
        paginated=True,
        incremental_param="created_after",
        incremental_fields=_epoch_incremental_field("created_on"),
        partition_key="created_on",
    ),
    "tests": TestrailEndpointConfig(
        name="tests",
        method="get_tests",
        scope="run",
        response_key="tests",
        # get_tests only filters by status_id and tests carry no timestamps, so full refresh.
        paginated=True,
    ),
    "results": TestrailEndpointConfig(
        name="results",
        method="get_results_for_run",
        scope="run",
        response_key="results",
        paginated=True,
        # get_results_for_run documents a created_after filter; results are append-only in
        # TestRail, so a created_on cursor is a genuine incremental sync.
        incremental_param="created_after",
        incremental_fields=_epoch_incremental_field("created_on"),
        partition_key="created_on",
    ),
    "statuses": TestrailEndpointConfig(
        name="statuses",
        method="get_statuses",
        scope="instance",
        response_key="statuses",
        paginated=False,
    ),
    "priorities": TestrailEndpointConfig(
        name="priorities",
        method="get_priorities",
        scope="instance",
        response_key="priorities",
        paginated=False,
    ),
    "case_types": TestrailEndpointConfig(
        name="case_types",
        method="get_case_types",
        scope="instance",
        response_key="case_types",
        paginated=False,
    ),
}

ENDPOINTS = tuple(TESTRAIL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TESTRAIL_ENDPOINTS.items()
}
