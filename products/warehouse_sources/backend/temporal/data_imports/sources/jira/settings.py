from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How an endpoint advances through pages:
# - "token":  Jira's enhanced search returns an opaque ``nextPageToken`` (issues only).
# - "offset": classic ``startAt`` / ``maxResults`` paging used by the ``*/search`` endpoints.
# - "none":   the endpoint returns the full collection in a single (un-paginated) response.
# - "custom": the endpoint has its own iterator in ``jira.py``.
PaginationMode = Literal["token", "offset", "none", "custom"]

DEFAULT_PAGE_SIZE = 100
# The Jira Software (agile) API caps ``maxResults`` at 50.
AGILE_PAGE_SIZE = 50
# Both ``/worklog/updated`` and ``/worklog/list`` cap a page at 1000 worklogs.
WORKLOG_PAGE_SIZE = 1000


@dataclass(frozen=True)
class JiraEndpointConfig:
    name: str
    path: str
    primary_key: list[str]
    pagination: PaginationMode
    # Key in the JSON response that holds the list of records. ``None`` means the
    # response body itself is the list (e.g. ``GET /field`` returns a bare array).
    data_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field used for partitioning. Must NOT change after creation
    # (so never ``updated``). ``None`` disables partitioning for the endpoint.
    partition_key: Optional[str] = None
    # Only ``issues`` exposes a genuine server-side timestamp filter (JQL ``updated >= ...``).
    supports_incremental: bool = False
    page_size: int = DEFAULT_PAGE_SIZE
    default_incremental_field: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Endpoint catalog. Jira Cloud REST API v3 (https://developer.atlassian.com/cloud/jira/platform/rest/v3/).
# We deliberately exclude the per-issue fan-out streams (comments, votes, watchers, remote links,
# properties, transitions) — each requires one HTTP request per issue and degrades badly on large
# instances. Worklogs avoid that through the instance-wide ``/worklog/updated`` feed. Issues carry the
# bulk of the useful data and sync incrementally.
JIRA_ENDPOINTS: dict[str, JiraEndpointConfig] = {
    "issues": JiraEndpointConfig(
        name="issues",
        # Enhanced JQL search. The legacy ``/search`` (startAt/maxResults) is deprecated.
        path="/rest/api/3/search/jql",
        primary_key=["id"],
        pagination="token",
        data_key="issues",
        supports_incremental=True,
        partition_key="created",
        incremental_fields=[_datetime_field("updated"), _datetime_field("created")],
    ),
    "projects": JiraEndpointConfig(
        name="projects",
        path="/rest/api/3/project/search",
        primary_key=["id"],
        pagination="offset",
        data_key="values",
    ),
    "users": JiraEndpointConfig(
        name="users",
        path="/rest/api/3/users/search",
        primary_key=["accountId"],
        pagination="offset",
        # Returns a bare array, no wrapper object.
        data_key=None,
    ),
    "fields": JiraEndpointConfig(
        name="fields",
        path="/rest/api/3/field",
        primary_key=["id"],
        pagination="none",
    ),
    "issue_types": JiraEndpointConfig(
        name="issue_types",
        path="/rest/api/3/issuetype",
        primary_key=["id"],
        pagination="none",
    ),
    "statuses": JiraEndpointConfig(
        name="statuses",
        path="/rest/api/3/status",
        primary_key=["id"],
        pagination="none",
    ),
    "priorities": JiraEndpointConfig(
        name="priorities",
        path="/rest/api/3/priority",
        primary_key=["id"],
        pagination="none",
    ),
    "resolutions": JiraEndpointConfig(
        name="resolutions",
        path="/rest/api/3/resolution",
        primary_key=["id"],
        pagination="none",
    ),
    "dashboards": JiraEndpointConfig(
        name="dashboards",
        path="/rest/api/3/dashboard",
        primary_key=["id"],
        pagination="offset",
        data_key="dashboards",
    ),
    "filters": JiraEndpointConfig(
        name="filters",
        path="/rest/api/3/filter/search",
        primary_key=["id"],
        pagination="offset",
        data_key="values",
    ),
    "worklogs": JiraEndpointConfig(
        name="worklogs",
        # Paged through ``/worklog/updated`` (ids, oldest update first), then hydrated in bulk with
        # ``POST /worklog/list``.
        path="/rest/api/3/worklog/updated",
        primary_key=["id"],
        pagination="custom",
        supports_incremental=True,
        partition_key="created",
        incremental_fields=[_datetime_field("updated")],
        default_incremental_field="updated",
        page_size=WORKLOG_PAGE_SIZE,
    ),
    "boards": JiraEndpointConfig(
        name="boards",
        path="/rest/agile/1.0/board",
        primary_key=["id"],
        pagination="offset",
        data_key="values",
        page_size=AGILE_PAGE_SIZE,
    ),
    "sprints": JiraEndpointConfig(
        name="sprints",
        path="/rest/agile/1.0/board/{boardId}/sprint",
        # A sprint is listed on every board whose filter matches its issues, so rows are deduplicated
        # by id across boards. ``originBoardId`` names the board that owns the sprint.
        primary_key=["id"],
        pagination="offset",
        data_key="values",
        page_size=AGILE_PAGE_SIZE,
        fanout=DependentEndpointConfig(
            parent_name="boards",
            resolve_param="boardId",
            resolve_field="id",
            include_from_parent=[],
            # Kanban boards answer 400 because they have no sprints. A board deleted after the
            # listing answers 404.
            child_response_actions=[
                {"status_code": 400, "action": "ignore"},
                {"status_code": 404, "action": "ignore"},
            ],
        ),
    ),
    "sprint_issues": JiraEndpointConfig(
        name="sprint_issues",
        # The agile ``/sprint/{sprintId}/issue`` listing is deprecated, so membership comes from the
        # Sprint field of each issue, read through the enhanced JQL search.
        path="/rest/api/3/search/jql",
        primary_key=["sprint_id", "issue_id"],
        pagination="custom",
        data_key="issues",
    ),
}

ENDPOINTS = tuple(JIRA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in JIRA_ENDPOINTS.items()
}
