from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

# SonarQube Cloud v1 web API host per region. The token and organization are region-bound, so the
# host the user picks decides which of these we hit. v2 (api.sonarcloud.io / api.sonarqube.us) is
# gradually replacing v1, but v1 is still the mature, documented surface for these resources.
REGION_HOSTS: dict[str, str] = {
    "eu": "https://sonarcloud.io/api",
    "us": "https://sonarqube.us/api",
}

# v1 search endpoints page via `p`/`ps` (max 500) and hard-cap the total result set at 10000 rows.
# We ask for the largest page and stop once the cap is reached; slicing past it would need date/facet
# windowing, which the v1 surface doesn't offer uniformly.
MAX_PAGE_SIZE = 500
RESULT_CAP = 10000

# measures/search_history pages the history points of each metric, up to 1000 per page.
HISTORY_PAGE_SIZE = 1000

# The metric values a code-quality dashboard reads. measures/component_tree accepts at most 15 metric
# keys per request, so the history table asks for the same 15 to keep the two tables joinable.
MEASURE_METRIC_KEYS = (
    "ncloc",
    "lines",
    "coverage",
    "lines_to_cover",
    "uncovered_lines",
    "duplicated_lines_density",
    "bugs",
    "vulnerabilities",
    "code_smells",
    "security_hotspots",
    "violations",
    "sqale_index",
    "reliability_rating",
    "security_rating",
    "sqale_rating",
)


@dataclass(frozen=False)
class SonarCloudEndpointConfig:
    name: str
    # v1 path relative to `<host>/api`, e.g. "issues/search".
    path: str
    # Key in the JSON response holding the row list (SonarQube Cloud wraps rows differently per resource).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["key"])
    # Most resources are scoped to a single organization; metric definitions are global. For a
    # fan-out table this says whether the child request takes the organization.
    requires_organization: bool = True
    # Stable creation-time field to partition by. Never an updated_at-style field, which would rewrite
    # partitions every sync. `None` disables partitioning for the endpoint.
    partition_key: Optional[str] = None
    # Some resources (quality gates) return a flat, unpaginated list.
    paginated: bool = True
    should_sync_default: bool = True
    # Set for tables read per parent row (per project or per issue). The parent's organization and
    # page size are added at request time.
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = MAX_PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


_METRIC_KEYS_PARAM: dict[str, Any] = {"metricKeys": ",".join(MEASURE_METRIC_KEYS)}


# Endpoint catalog. Every stream is full refresh: SonarQube Cloud exposes no uniform server-side update
# cursor. measures/search_history takes a `from` date, but its dates are analysis dates that become
# readable only after background processing, and the per-project reads form no single ordered series,
# so a max-date watermark could skip analyses.
SONAR_CLOUD_ENDPOINTS: dict[str, SonarCloudEndpointConfig] = {
    "projects": SonarCloudEndpointConfig(
        name="projects",
        path="components/search_projects",
        data_key="components",
    ),
    "issues": SonarCloudEndpointConfig(
        name="issues",
        path="issues/search",
        data_key="issues",
        partition_key="creationDate",
    ),
    "metrics": SonarCloudEndpointConfig(
        name="metrics",
        path="metrics/search",
        data_key="metrics",
        requires_organization=False,
    ),
    "quality_gates": SonarCloudEndpointConfig(
        name="quality_gates",
        path="qualitygates/list",
        data_key="qualitygates",
        primary_keys=["id"],
        paginated=False,
    ),
    "rules": SonarCloudEndpointConfig(
        name="rules",
        path="rules/search",
        data_key="rules",
    ),
    "quality_profiles": SonarCloudEndpointConfig(
        name="quality_profiles",
        path="qualityprofiles/search",
        data_key="profiles",
        paginated=False,
    ),
    # Current metric values per component (the project itself, its directories and its files).
    "measures": SonarCloudEndpointConfig(
        name="measures",
        path="measures/component_tree?component={component}",
        requires_organization=False,
        # The project row sits in `baseComponent`, the descendants in `components`. `paging` is
        # selected too so the match is never a single object, which the client would unwrap.
        data_key="($.paging) | ($.baseComponent) | ($.components[*])",
        primary_keys=["key", "metric"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="component",
            resolve_field="key",
            include_from_parent=["key"],
            parent_field_renames={"key": "project_key"},
            child_params={**_METRIC_KEYS_PARAM, "strategy": "all", "ps": MAX_PAGE_SIZE},
        ),
    ),
    # One row per project, metric and analysis.
    "measures_history": SonarCloudEndpointConfig(
        name="measures_history",
        path="measures/search_history?component={component}",
        requires_organization=False,
        data_key="measures",
        primary_keys=["project_key", "metric", "date"],
        partition_key="date",
        page_size=HISTORY_PAGE_SIZE,
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="component",
            resolve_field="key",
            include_from_parent=["key"],
            parent_field_renames={"key": "project_key"},
            child_params={"metrics": _METRIC_KEYS_PARAM["metricKeys"], "ps": HISTORY_PAGE_SIZE},
        ),
    ),
    # One request per issue, so this table is off by default.
    "issue_changelog": SonarCloudEndpointConfig(
        name="issue_changelog",
        path="issues/changelog?issue={issue}",
        requires_organization=False,
        data_key="changelog",
        primary_keys=["issue_key", "creationDate"],
        partition_key="creationDate",
        paginated=False,
        should_sync_default=False,
        fanout=DependentEndpointConfig(
            parent_name="issues",
            resolve_param="issue",
            resolve_field="key",
            include_from_parent=["key", "project"],
            parent_field_renames={"key": "issue_key", "project": "project_key"},
        ),
    ),
    # The component inventory of each project: its directories, files and test files.
    "components": SonarCloudEndpointConfig(
        name="components",
        path="components/tree?component={component}",
        requires_organization=False,
        data_key="components",
        primary_keys=["project_key", "key"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="component",
            resolve_field="key",
            include_from_parent=["key"],
            parent_field_renames={"key": "project_key"},
            child_params={"strategy": "all", "ps": MAX_PAGE_SIZE},
        ),
    ),
    # The quality profile each project uses per language. qualityprofiles/projects is not used: it
    # lists only projects bound to a profile explicitly, not the ones on the language's default profile.
    "project_quality_profiles": SonarCloudEndpointConfig(
        name="project_quality_profiles",
        path="qualityprofiles/search?project={project}",
        data_key="profiles",
        primary_keys=["project_key", "key"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project",
            resolve_field="key",
            include_from_parent=["key"],
            parent_field_renames={"key": "project_key"},
        ),
    ),
    "pull_requests": SonarCloudEndpointConfig(
        name="pull_requests",
        path="project_pull_requests/list?project={project}",
        requires_organization=False,
        data_key="pullRequests",
        primary_keys=["project_key", "key"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project",
            resolve_field="key",
            include_from_parent=["key"],
            parent_field_renames={"key": "project_key"},
        ),
    ),
}

ENDPOINTS = tuple(SONAR_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SONAR_CLOUD_ENDPOINTS.items()
}
