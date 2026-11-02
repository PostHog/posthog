from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


class BugsnagScope(Enum):
    """Where an endpoint lives in BugSnag's resource hierarchy.

    The Data Access API is nested: a personal auth token grants access to one or more
    organizations, each organization owns projects, and most analytical resources
    (errors, events, releases, …) are scoped to a project. So fetching a project-scoped
    table means walking ``organizations -> projects -> <endpoint>``.
    """

    # Top-level collection reachable directly from the token (GET /user/organizations).
    ORGANIZATION = "organization"
    # Fan out over every organization the token can see (GET /organizations/{organization_id}/...).
    PER_ORG = "per_org"
    # Fan out over every project in every organization (GET /projects/{project_id}/...).
    PER_PROJECT = "per_project"
    # Fan out over every (project, release stage) pair. Release-stage-scoped endpoints require the
    # stage as a query parameter; the stages a project has seen come back on the project itself.
    PER_PROJECT_RELEASE_STAGE = "per_project_release_stage"
    # Fan out over every (project, pivot) pair, where the pivots are the ones the `pivots` endpoint
    # lists for that project.
    PER_PROJECT_PIVOT = "per_project_pivot"
    # Fan out over every (project, error) pair. Error-grain endpoints cost one request per error and
    # BugSnag offers no filter to narrow the error list, so the fan-out is capped.
    PER_PROJECT_ERROR = "per_project_error"
    # Fan out over every (project, error, pivot) triple, for the error-grain breakdown endpoints.
    PER_PROJECT_ERROR_PIVOT = "per_project_error_pivot"
    # Fan out over every (project, span group) pair, where the span groups are the ones the
    # `span_groups` endpoint lists for that project.
    PER_PROJECT_SPAN_GROUP = "per_project_span_group"


@dataclass(frozen=True)
class BugsnagEndpointConfig:
    name: str
    scope: BugsnagScope
    # Path template. PER_ORG paths contain ``{organization_id}``; PER_PROJECT paths contain
    # ``{project_id}``. ORGANIZATION paths are static.
    path: str
    # Primary key columns used for merge dedup. For fan-out children the parent identifier is
    # included (and injected into every row) so the key is unique across the whole table — the
    # API only guarantees ids are unique within a parent resource.
    primary_keys: list[str]
    # Stable, creation-time datetime column to partition by. Never a `last_seen`/`updated_at`
    # style field — those move and would rewrite partitions every sync. None disables partitioning.
    partition_key: Optional[str] = None
    # per_page value used when paginating this endpoint. Most list endpoints accept up to 100, but
    # a few cap lower and hard-reject an over-max value with a 400 instead of clamping, so those
    # need their own limit. None omits the parameter, for endpoints that return a fixed-size result.
    page_size: Optional[int] = 100
    # Static query parameters every request to this endpoint carries.
    params: dict[str, str] = field(default_factory=dict)
    # When set, the endpoint returns a single JSON object instead of a list, and each item of the
    # named nested array becomes a row carrying the object's own scalar fields.
    object_row_field: Optional[str] = None
    # Statuses meaning "this parent has no data here" rather than "the sync is broken". Fanning out
    # over every project reaches projects the endpoint has nothing for, so those are skipped.
    missing_data_statuses: tuple[int, ...] = ()
    # Whether the endpoint pages by a numeric row `offset` instead of the Link header. The
    # performance (span) endpoints send no Link header, so a short page is the only end-of-data
    # signal there.
    paginate_by_offset: bool = False
    # Hard page cap per fan-out parent. Guards endpoints whose result size follows the cardinality
    # of user-supplied data rather than anything the API bounds.
    max_pages: Optional[int] = None
    # Cap on how many fan-out parents a single project contributes. Release stages and pivots are
    # both derived from client-reported event data, so nothing in the API bounds how many a project
    # accumulates — a misconfigured reporter alone can add one per build.
    max_parents_per_project: Optional[int] = None
    # Cap on how many of a project's errors an error-grain endpoint fans out over, taken from the
    # most recently seen end of the error list. Separate from `max_parents_per_project` so an
    # endpoint that crosses errors with a second dimension can bound each independently.
    max_errors_per_project: Optional[int] = None
    # The menu of incremental cursor candidates advertised to the user. Empty = full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Whether the table is selected for sync by default in the connection wizard.
    should_sync_default: bool = True


# BugSnag's id values are 24-character hex ObjectIds that are globally unique, but the Data Access
# API documents uniqueness only within a parent resource. We therefore include the parent id in
# every fan-out child's primary key (and inject it into the row) so merge dedup stays correct even
# if that assumption ever breaks — a redundant-but-safe composite never seeds duplicate rows.
BUGSNAG_ENDPOINTS: dict[str, BugsnagEndpointConfig] = {
    "organizations": BugsnagEndpointConfig(
        name="organizations",
        scope=BugsnagScope.ORGANIZATION,
        path="/user/organizations",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "projects": BugsnagEndpointConfig(
        name="projects",
        scope=BugsnagScope.PER_ORG,
        path="/organizations/{organization_id}/projects",
        primary_keys=["id", "organization_id"],
        partition_key="created_at",
    ),
    "collaborators": BugsnagEndpointConfig(
        name="collaborators",
        scope=BugsnagScope.PER_ORG,
        path="/organizations/{organization_id}/collaborators",
        primary_keys=["id", "organization_id"],
    ),
    "teams": BugsnagEndpointConfig(
        name="teams",
        scope=BugsnagScope.PER_ORG,
        path="/organizations/{organization_id}/teams",
        primary_keys=["id", "organization_id"],
    ),
    "errors": BugsnagEndpointConfig(
        name="errors",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/errors",
        primary_keys=["id", "project_id"],
        partition_key="first_seen",
    ),
    # Events can be very large (one row per captured event), so it's off by default to avoid a
    # surprise full-history sync. Enable deliberately when raw event-level data is needed.
    "events": BugsnagEndpointConfig(
        name="events",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/events",
        primary_keys=["id", "project_id"],
        partition_key="received_at",
        should_sync_default=False,
    ),
    "releases": BugsnagEndpointConfig(
        name="releases",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/releases",
        primary_keys=["id", "project_id"],
        partition_key="released_at",
        # This endpoint caps per_page at 10 and returns 400 for anything higher.
        page_size=10,
    ),
    "pivots": BugsnagEndpointConfig(
        name="pivots",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/pivots",
        primary_keys=["event_field_display_id", "project_id"],
        should_sync_default=False,
    ),
    "event_fields": BugsnagEndpointConfig(
        name="event_fields",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/event_fields",
        primary_keys=["display_id", "project_id"],
        should_sync_default=False,
    ),
    "trace_fields": BugsnagEndpointConfig(
        name="trace_fields",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/trace_fields",
        primary_keys=["display_id", "project_id"],
        should_sync_default=False,
    ),
    # The same breakdown values as `pivot_values`, narrowed to one error, which answers "which
    # users did this error affect". Every (error, pivot) pair is its own request, so both dimensions
    # are capped and the table is off by default.
    "error_pivot_values": BugsnagEndpointConfig(
        name="error_pivot_values",
        scope=BugsnagScope.PER_PROJECT_ERROR_PIVOT,
        path="/projects/{project_id}/errors/{error_id}/pivots/{event_field_display_id}/values",
        primary_keys=["project_id", "error_id", "event_field_display_id", "event_field_value"],
        page_size=30,
        # Sorted results are truncated with error code 60000 once there are too many of them, and
        # the API documents `unsorted` as the way to read a pivot's values in full.
        params={"sort": "unsorted"},
        # An error deleted or merged away between listing and fan-out answers 404.
        missing_data_statuses=(404,),
        max_pages=100,
        max_errors_per_project=10,
        max_parents_per_project=100,
        should_sync_default=False,
    ),
    "saved_searches": BugsnagEndpointConfig(
        name="saved_searches",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/saved_searches",
        primary_keys=["id", "project_id"],
    ),
    # One row per UTC day per project for the last 30 days, flattened out of the single object the
    # endpoint returns. Projects with no sessions answer 204 or 404 and are skipped.
    "stability_trend": BugsnagEndpointConfig(
        name="stability_trend",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/stability_trend",
        primary_keys=["project_id", "bucket_start"],
        partition_key="bucket_start",
        page_size=None,
        object_row_field="timeline_points",
        missing_data_statuses=(404,),
    ),
    # Bucketed event counts for the project as a whole. `resolution` gives fixed-width buckets, so
    # re-syncs merge onto the same boundaries instead of accumulating shifted ones; 12h keeps the
    # point count far below the endpoint's 2000-point ceiling.
    "trend": BugsnagEndpointConfig(
        name="trend",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/trend",
        primary_keys=["project_id", "from"],
        partition_key="from",
        page_size=None,
        params={"resolution": "12h"},
    ),
    # The same bucketed counts as `trend`, but per error rather than per project. Error grain costs
    # one request per error and the endpoint takes no time filter, so the fan-out is capped at the
    # project's most recently seen errors and the table is off by default.
    "error_trend": BugsnagEndpointConfig(
        name="error_trend",
        scope=BugsnagScope.PER_PROJECT_ERROR,
        path="/projects/{project_id}/errors/{error_id}/trend",
        primary_keys=["project_id", "error_id", "from"],
        partition_key="from",
        page_size=None,
        params={"resolution": "12h"},
        # An error deleted or merged away between listing and fan-out answers 404.
        missing_data_statuses=(404,),
        max_errors_per_project=25,
        should_sync_default=False,
    ),
    "release_groups": BugsnagEndpointConfig(
        name="release_groups",
        scope=BugsnagScope.PER_PROJECT_RELEASE_STAGE,
        path="/projects/{project_id}/release_groups",
        primary_keys=["id", "project_id"],
        partition_key="first_released_at",
        # The endpoint documents 30 per page and no maximum, so stay on the documented value.
        page_size=30,
        max_parents_per_project=25,
    ),
    # The breakdown values behind each pivot. Cardinality follows the underlying event field — a
    # user-id pivot has a value per user — so it is off by default and capped per pivot.
    "pivot_values": BugsnagEndpointConfig(
        name="pivot_values",
        scope=BugsnagScope.PER_PROJECT_PIVOT,
        path="/projects/{project_id}/pivots/{event_field_display_id}/values",
        primary_keys=["project_id", "event_field_display_id", "event_field_value"],
        page_size=30,
        # Sorted results are truncated with error code 60000 once there are too many of them, and
        # the API documents `unsorted` as the way to read a pivot's values in full.
        params={"sort": "unsorted"},
        max_pages=100,
        max_parents_per_project=25,
        should_sync_default=False,
    ),
    # BugSnag Performance aggregates: one row per operation (app start, page load, network request,
    # custom timing) with its duration percentiles and span counts. Sorted by name so the offset
    # cursor stays put while a sync walks it, because the ranking sorts shift as spans arrive.
    "span_groups": BugsnagEndpointConfig(
        name="span_groups",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/span_groups",
        primary_keys=["id", "project_id"],
        params={"sort": "name", "direction": "asc"},
        # Projects without BugSnag Performance have no span groups to list.
        missing_data_statuses=(404,),
        paginate_by_offset=True,
        max_pages=100,
    ),
    # Individual spans under each span group, the event grain of BugSnag Performance. The endpoint
    # takes no offset or cursor, so one request per span group returns the most recent page and
    # nothing more. The table is a recent-spans sample rather than the full history, and is off by
    # default because it still costs a request per group.
    "span_group_spans": BugsnagEndpointConfig(
        name="span_group_spans",
        scope=BugsnagScope.PER_PROJECT_SPAN_GROUP,
        path="/projects/{project_id}/span_groups/{span_group_id}/spans",
        primary_keys=["project_id", "span_group_id", "id"],
        partition_key="timestamp",
        params={"sort": "timestamp", "direction": "desc"},
        # Projects without BugSnag Performance have no spans to list.
        missing_data_statuses=(404,),
        max_pages=1,
        max_parents_per_project=50,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(BUGSNAG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUGSNAG_ENDPOINTS.items()
}
