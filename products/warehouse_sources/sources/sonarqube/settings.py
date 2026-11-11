from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# SonarQube caps `ps` (page size) at 500 on virtually every list endpoint.
PAGE_SIZE = 500

# /api/issues/search rejects any request where `p * ps` exceeds 10,000. To read past it we
# re-window using `createdAfter` set to the last issue's creation date and start paging again.
ISSUES_MAX_RESULTS = 10_000

# /api/measures/component_tree caps `metricKeys` at 15 keys from 6.3 (75 from 10.8), so request the
# metric catalog in chunks small enough for every supported server.
METRIC_KEYS_PER_REQUEST = 15

# Metric value types the measures tables skip. component_tree rejects DISTRIB outright and accepts only
# a few DATA metrics, whose values are serialized structures rather than numbers.
UNSUPPORTED_METRIC_TYPES = frozenset({"DISTRIB", "DATA"})

# /api/measures/search_history pages over the history points of each metric and allows up to 1,000.
HISTORY_PAGE_SIZE = 1_000


def _created_at_incremental_fields() -> list[IncrementalField]:
    # /api/issues/search only exposes a creation-time server filter (`createdAfter`), keyed on
    # each issue's `creationDate`. There is no server-side "updated since" filter, so incremental
    # syncs pick up newly created issues; status changes on old issues are only reflected on a
    # full refresh.
    return [
        {
            "label": "creationDate",
            "type": IncrementalFieldType.DateTime,
            "field": "creationDate",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


def _history_date_incremental_fields() -> list[IncrementalField]:
    # /api/measures/search_history and /api/project_analyses/search filter server-side with `from`
    # on each analysis date.
    return [
        {
            "label": "date",
            "type": IncrementalFieldType.DateTime,
            "field": "date",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass(frozen=True)
class ProjectFanout:
    # How the per-project request and rows are built; `sonarqube.py` dispatches on it.
    kind: Literal["quality_gate_status", "hotspots", "component_measures", "measures_history", "project_rows"]
    # Query param names that carry the project key.
    project_params: tuple[str, ...] = ("component",)
    page_size: int = PAGE_SIZE
    # Hard per-project page cap for endpoints that refuse p*ps beyond 10,000. None means no cap.
    max_pages: Optional[int] = None


@dataclass(frozen=False)
class SonarqubeEndpointConfig:
    name: str
    path: str  # Path under the instance base URL, e.g. "/api/issues/search"
    response_key: str  # Root key of the list in the JSON response
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field to partition by. None when the resource has no reliable created_at.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["key"])
    # Query params merged into every request for this endpoint (e.g. a required qualifier).
    extra_params: dict[str, str] = field(default_factory=dict)
    # issues/search hard-caps results at p*ps<=10000; walk past it by re-windowing on createdAfter.
    windowed_incremental: bool = False
    # False for endpoints that return the whole list in one response with no `p`/`ps` paging.
    paginated: bool = True
    # Fan-out endpoints run once per project (see `ProjectFanout`); None for top-level list endpoints.
    fanout: Optional[ProjectFanout] = None
    # Runs once per issue of the issues endpoint, for endpoints that take a single issue key.
    per_issue: bool = False
    should_sync_default: bool = True


SONARQUBE_ENDPOINTS: dict[str, SonarqubeEndpointConfig] = {
    # Projects the token can see. /api/components/search with qualifiers=TRK lists projects and
    # only needs the browse permission, unlike /api/projects/search which requires Administer System.
    "projects": SonarqubeEndpointConfig(
        name="projects",
        path="/api/components/search",
        response_key="components",
        extra_params={"qualifiers": "TRK"},
    ),
    # Metric definitions — a small reference set that changes rarely, so full refresh each run.
    "metrics": SonarqubeEndpointConfig(
        name="metrics",
        path="/api/metrics/search",
        response_key="metrics",
    ),
    # Coding rules catalog — reference data used to interpret issues. Full refresh.
    "rules": SonarqubeEndpointConfig(
        name="rules",
        path="/api/rules/search",
        response_key="rules",
    ),
    # Issues (code smells, bugs, vulnerabilities). The core time series. `createdAfter` filters
    # server-side on creationDate; sorting ascending by CREATION_DATE lets us both sync
    # incrementally and re-window past the 10,000-result ceiling.
    "issues": SonarqubeEndpointConfig(
        name="issues",
        path="/api/issues/search",
        response_key="issues",
        supports_incremental=True,
        incremental_fields=_created_at_incremental_fields(),
        partition_key="creationDate",
        windowed_incremental=True,
    ),
    # Quality gate definitions. The endpoint returns every gate in one unpaged response, and gates
    # have had no id since SonarQube 10.0, so the name is the key.
    "quality_gates": SonarqubeEndpointConfig(
        name="quality_gates",
        path="/api/qualitygates/list",
        response_key="qualitygates",
        primary_keys=["name"],
        paginated=False,
    ),
    # Current quality gate status (pass/fail plus each condition) of every project's main branch.
    "project_quality_gate_status": SonarqubeEndpointConfig(
        name="project_quality_gate_status",
        path="/api/qualitygates/project_status",
        response_key="projectStatus",
        primary_keys=["projectKey"],
        paginated=False,
        fanout=ProjectFanout(kind="quality_gate_status", project_params=("projectKey",)),
    ),
    # Security hotspots per project. No server-side date filter, so full refresh. SonarQube 10.2
    # renamed `projectKey` to `project` and 2026.5 removed the old name; the server ignores a param
    # it does not read, so sending both works on every version.
    "hotspots": SonarqubeEndpointConfig(
        name="hotspots",
        path="/api/hotspots/search",
        response_key="hotspots",
        partition_key="creationDate",
        fanout=ProjectFanout(
            kind="hotspots",
            project_params=("project", "projectKey"),
            max_pages=ISSUES_MAX_RESULTS // PAGE_SIZE,
        ),
    ),
    # Current value of every metric on every component (project, directories, files) of each project,
    # one row per component and metric. Row count grows with files x metrics, so it is off by default.
    "component_measures": SonarqubeEndpointConfig(
        name="component_measures",
        path="/api/measures/component_tree",
        response_key="components",
        primary_keys=["component", "metric"],
        extra_params={"strategy": "all"},
        should_sync_default=False,
        fanout=ProjectFanout(kind="component_measures"),
    ),
    # Value of every metric at each analysis of each project, one row per project, metric and date.
    "measures_history": SonarqubeEndpointConfig(
        name="measures_history",
        path="/api/measures/search_history",
        response_key="measures",
        primary_keys=["project", "metric", "date"],
        supports_incremental=True,
        incremental_fields=_history_date_incremental_fields(),
        partition_key="date",
        fanout=ProjectFanout(kind="measures_history", page_size=HISTORY_PAGE_SIZE),
    ),
    # Analyses of each project's main branch, with their version and event markers. `from` filters
    # server-side on the analysis date. The key is the analysis UUID, unique across the instance.
    "project_analyses": SonarqubeEndpointConfig(
        name="project_analyses",
        path="/api/project_analyses/search",
        response_key="analyses",
        supports_incremental=True,
        incremental_fields=_history_date_incremental_fields(),
        partition_key="date",
        fanout=ProjectFanout(kind="project_rows", project_params=("project",)),
    ),
    # Branches of each project, with their quality gate status and last analysis date. Unpaged.
    "project_branches": SonarqubeEndpointConfig(
        name="project_branches",
        path="/api/project_branches/list",
        response_key="branches",
        primary_keys=["project", "name"],
        paginated=False,
        fanout=ProjectFanout(kind="project_rows", project_params=("project",)),
    ),
    # Pull requests of each project, with their quality gate status. Unpaged. Only Developer Edition
    # and above serve this endpoint; Community Build answers 404, which leaves the table empty.
    "project_pull_requests": SonarqubeEndpointConfig(
        name="project_pull_requests",
        path="/api/project_pull_requests/list",
        response_key="pullRequests",
        primary_keys=["project", "key"],
        paginated=False,
        fanout=ProjectFanout(kind="project_rows", project_params=("project",)),
    ),
    # Change history of every issue, one row per change. The endpoint takes one issue per request
    # and has no date filter, so a sync makes one request per issue; it is off by default. Changes
    # come sorted by date and carry no id, so a change is keyed on its position in the issue's list.
    "issue_changelog": SonarqubeEndpointConfig(
        name="issue_changelog",
        path="/api/issues/changelog",
        response_key="changelog",
        primary_keys=["issue", "changeIndex"],
        partition_key="creationDate",
        paginated=False,
        per_issue=True,
        should_sync_default=False,
    ),
    # Users. /api/users/search requires Administer System permission, so it's off by default —
    # a token without it can still sync everything else.
    "users": SonarqubeEndpointConfig(
        name="users",
        path="/api/users/search",
        response_key="users",
        primary_keys=["login"],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(SONARQUBE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SONARQUBE_ENDPOINTS.items()
}
