from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ParentRowFilter
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DEFAULT_SENTRY_API_BASE_URL = "https://sentry.io"
ALLOWED_SENTRY_API_BASE_URLS = (
    DEFAULT_SENTRY_API_BASE_URL,
    "https://us.sentry.io",
    "https://de.sentry.io",
)

# Scopes a Sentry auth token needs to sync every dataset. Single source of truth for
# the setup caption and the "missing scopes" credential errors, so the list we tell
# users to grant can't drift from the list we check against.
REQUIRED_SENTRY_SCOPES = (
    "alerts:read",
    "event:read",
    "member:read",
    "org:integrations",
    "org:read",
    "project:read",
    "team:read",
)

# Sentry's time-series endpoints (sessions, stats, replays, Discover events) reject
# ranges older than the organization's event retention window, so every request has to
# carry a floor rather than the 1970 sentinel the issue endpoints tolerate.
SENTRY_RETENTION_DAYS = 90

# The issues listing only returns issues whose events still exist in Sentry's event store,
# and events are kept for the org's plan retention (30 or 90 days) — a per-customer bound
# that is unqueryable and clamps any wider request. A snapshot scan cannot reproduce it, so
# issue_events and issue_hashes stay on parent_source="api", and issue_tag_values reads the
# warehouse only when an incremental watermark bounds the scan, with this window as the cap.
SENTRY_FANOUT_PARENT_WINDOW = timedelta(days=90)

ISSUES_PARENT_ROW_FILTER = ParentRowFilter(field="lastSeen", not_older_than=SENTRY_FANOUT_PARENT_WINDOW)

# `dataset` values accepted by /trace-items/attributes/.
TRACE_ITEM_DATASETS = ("logs", "preprod", "processing_errors", "spans", "tracemetrics")
# `itemType` values accepted by /trace-items/stats/.
TRACE_ITEM_STATS_TYPES = ("spans", "occurrences")
# `stat` values accepted by the per-project stats endpoint.
PROJECT_STAT_NAMES = ("received", "rejected", "blacklisted", "generated")

LAST_SEEN_INCREMENTAL: IncrementalField = {
    "label": "lastSeen",
    "type": IncrementalFieldType.DateTime,
    "field": "lastSeen",
    "field_type": IncrementalFieldType.DateTime,
}
FIRST_SEEN_INCREMENTAL: IncrementalField = {
    "label": "firstSeen",
    "type": IncrementalFieldType.DateTime,
    "field": "firstSeen",
    "field_type": IncrementalFieldType.DateTime,
}
DATE_RECEIVED_INCREMENTAL: IncrementalField = {
    "label": "dateReceived",
    "type": IncrementalFieldType.DateTime,
    "field": "dateReceived",
    "field_type": IncrementalFieldType.DateTime,
}

STARTED_AT_INCREMENTAL: IncrementalField = {
    "label": "started_at",
    "type": IncrementalFieldType.DateTime,
    "field": "started_at",
    "field_type": IncrementalFieldType.DateTime,
}
TIMESTAMP_INCREMENTAL: IncrementalField = {
    "label": "timestamp",
    "type": IncrementalFieldType.DateTime,
    "field": "timestamp",
    "field_type": IncrementalFieldType.DateTime,
}
INTERVAL_START_INCREMENTAL: IncrementalField = {
    "label": "interval_start",
    "type": IncrementalFieldType.DateTime,
    "field": "interval_start",
    "field_type": IncrementalFieldType.DateTime,
}
EPOCH_TIMESTAMP_INCREMENTAL: IncrementalField = {
    "label": "timestamp",
    "type": IncrementalFieldType.Integer,
    "field": "timestamp",
    "field_type": IncrementalFieldType.Integer,
}

ISSUES_INCREMENTAL_FIELDS: list[IncrementalField] = [LAST_SEEN_INCREMENTAL, FIRST_SEEN_INCREMENTAL]
DATE_RECEIVED_INCREMENTAL_FIELD: list[IncrementalField] = [
    DATE_RECEIVED_INCREMENTAL,
]
LAST_SEEN_INCREMENTAL_FIELD: list[IncrementalField] = [
    LAST_SEEN_INCREMENTAL,
]
STARTED_AT_INCREMENTAL_FIELD: list[IncrementalField] = [
    STARTED_AT_INCREMENTAL,
]
TIMESTAMP_INCREMENTAL_FIELD: list[IncrementalField] = [
    TIMESTAMP_INCREMENTAL,
]
INTERVAL_START_INCREMENTAL_FIELD: list[IncrementalField] = [
    INTERVAL_START_INCREMENTAL,
]
EPOCH_TIMESTAMP_INCREMENTAL_FIELD: list[IncrementalField] = [
    EPOCH_TIMESTAMP_INCREMENTAL,
]


@dataclass
class SentryEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = 100
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None
    # Static query params sent on every request for this endpoint.
    params: dict[str, Any] = field(default_factory=dict)
    # JSONPath to the row list when the payload wraps it (e.g. `{"data": [...]}`).
    data_selector: str | None = None
    # Query param carrying the page size. Endpoints whose spec documents no page-size
    # param set this to None so we don't send one.
    page_size_param: str | None = "limit"
    # Endpoints whose payload can't be paginated straight into rows and are handled by a
    # bespoke iterator in `sentry.py` instead of the shared REST resource path.
    custom_iterator: bool = False
    # Incremental windows on retention-bounded endpoints must be floored to
    # SENTRY_RETENTION_DAYS rather than starting from the 1970 sentinel.
    retention_bounded: bool = False


SENTRY_ENDPOINTS: dict[str, SentryEndpointConfig] = {
    "projects": SentryEndpointConfig(
        name="projects",
        path="/organizations/{organization_slug}/projects/",
        incremental_fields=[],
        partition_key="date_created",
    ),
    "teams": SentryEndpointConfig(
        name="teams",
        path="/organizations/{organization_slug}/teams/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key="id",
    ),
    "members": SentryEndpointConfig(
        name="members",
        path="/organizations/{organization_slug}/members/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key="id",
    ),
    "releases": SentryEndpointConfig(
        name="releases",
        path="/organizations/{organization_slug}/releases/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key="version",
    ),
    "environments": SentryEndpointConfig(
        name="environments",
        path="/organizations/{organization_slug}/environments/",
        incremental_fields=[],
        primary_key="id",
    ),
    "monitors": SentryEndpointConfig(
        name="monitors",
        path="/organizations/{organization_slug}/monitors/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key="id",
    ),
    "issues": SentryEndpointConfig(
        name="issues",
        path="/organizations/{organization_slug}/issues/",
        incremental_fields=ISSUES_INCREMENTAL_FIELDS,
        default_incremental_field="lastSeen",
        partition_key="first_seen",
        sort_mode="desc",
    ),
    "project_events": SentryEndpointConfig(
        name="project_events",
        path="/projects/{organization_slug}/{project_slug}/events/",
        # full=true (below) makes Sentry return the full event body, which carries a
        # `dateReceived` timestamp rather than the `dateCreated` field the lightweight
        # issue/event list serializers use.
        incremental_fields=DATE_RECEIVED_INCREMENTAL_FIELD,
        default_incremental_field="dateReceived",
        partition_key="date_received",
        primary_key=["project_id", "event_id"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
            # full=true makes Sentry return complete event bodies (incl. stacktrace entries).
            child_params={"full": "true"},
        ),
    ),
    "project_users": SentryEndpointConfig(
        name="project_users",
        path="/projects/{organization_slug}/{project_slug}/users/",
        incremental_fields=[],
        primary_key=["project_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
    "project_client_keys": SentryEndpointConfig(
        name="project_client_keys",
        path="/projects/{organization_slug}/{project_slug}/keys/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key=["project_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
    "project_service_hooks": SentryEndpointConfig(
        name="project_service_hooks",
        path="/projects/{organization_slug}/{project_slug}/hooks/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key=["project_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
    "issue_events": SentryEndpointConfig(
        name="issue_events",
        path="/organizations/{organization_slug}/issues/{issue_id}/events/",
        # full=true (below) makes Sentry return the full event body, which carries a
        # `dateReceived` timestamp rather than the `dateCreated` field the lightweight
        # issue/event list serializers use.
        incremental_fields=DATE_RECEIVED_INCREMENTAL_FIELD,
        default_incremental_field="dateReceived",
        partition_key="date_received",
        primary_key=["issue_id", "event_id"],
        fanout=DependentEndpointConfig(
            parent_name="issues",
            resolve_param="issue_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "issue_id"},
            parent_params={"query": "", "sort": "date"},
            # full=true makes Sentry return complete event bodies (incl. stacktrace entries).
            child_params={"full": "true"},
            # Not "warehouse": the issues listing is clamped by per-org event retention, which a
            # snapshot scan cannot reproduce — see SENTRY_FANOUT_PARENT_WINDOW.
            parent_source="api",
        ),
    ),
    "issue_hashes": SentryEndpointConfig(
        name="issue_hashes",
        path="/organizations/{organization_slug}/issues/{issue_id}/hashes/",
        incremental_fields=[],
        primary_key=["issue_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="issues",
            resolve_param="issue_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "issue_id"},
            parent_params={"query": "", "sort": "date"},
            # An issue can be deleted or merged into another between the `issues` listing and
            # this per-issue fetch, which 404s. That's expected churn, not a broken sync — treat
            # it as "no hashes for this issue" instead of failing the whole schema.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
            # Not "warehouse": same per-org retention clamp as issue_events.
            parent_source="api",
        ),
    ),
    "issue_tag_values": SentryEndpointConfig(
        name="issue_tag_values",
        path="/organizations/{organization_slug}/issues/{issue_id}/tags/{tag_key}/values/",
        incremental_fields=LAST_SEEN_INCREMENTAL_FIELD,
        default_incremental_field="lastSeen",
        partition_key="first_seen",
        sort_mode="desc",
        primary_key=["issue_id", "tag_key", "value"],
        custom_iterator=True,
    ),
    # --- Org-level flat endpoints ---
    "repos": SentryEndpointConfig(
        name="repos",
        path="/organizations/{organization_slug}/repos/",
        incremental_fields=[],
        partition_key="date_created",
        page_size_param=None,
    ),
    "dashboards": SentryEndpointConfig(
        name="dashboards",
        path="/organizations/{organization_slug}/dashboards/",
        incremental_fields=[],
        partition_key="date_created",
        page_size_param="per_page",
    ),
    "discover_saved_queries": SentryEndpointConfig(
        name="discover_saved_queries",
        path="/organizations/{organization_slug}/discover/saved/",
        incremental_fields=[],
        partition_key="date_created",
        page_size_param="per_page",
    ),
    "workflows": SentryEndpointConfig(
        name="workflows",
        path="/organizations/{organization_slug}/workflows/",
        incremental_fields=[],
        partition_key="date_created",
        page_size_param=None,
    ),
    "detectors": SentryEndpointConfig(
        name="detectors",
        path="/organizations/{organization_slug}/detectors/",
        incremental_fields=[],
        partition_key="date_created",
        page_size_param=None,
    ),
    "organization_tags": SentryEndpointConfig(
        name="organization_tags",
        path="/organizations/{organization_slug}/tags/",
        incremental_fields=[],
        primary_key="key",
        page_size_param=None,
    ),
    "integrations": SentryEndpointConfig(
        name="integrations",
        path="/organizations/{organization_slug}/integrations/",
        incremental_fields=[],
        page_size_param=None,
    ),
    "sentry_app_installations": SentryEndpointConfig(
        name="sentry_app_installations",
        path="/organizations/{organization_slug}/sentry-app-installations/",
        incremental_fields=[],
        primary_key="uuid",
        page_size_param=None,
    ),
    "replays": SentryEndpointConfig(
        name="replays",
        path="/organizations/{organization_slug}/replays/",
        incremental_fields=STARTED_AT_INCREMENTAL_FIELD,
        default_incremental_field="started_at",
        partition_key="started_at",
        params={"sort": "started_at"},
        data_selector="data",
        page_size_param="per_page",
        retention_bounded=True,
    ),
    "organization_events": SentryEndpointConfig(
        name="organization_events",
        path="/organizations/{organization_slug}/events/",
        incremental_fields=TIMESTAMP_INCREMENTAL_FIELD,
        default_incremental_field="timestamp",
        partition_key="timestamp",
        params={
            "dataset": "errors",
            "field": ["id", "timestamp", "transaction"],
            "sort": "timestamp",
        },
        data_selector="data",
        page_size_param="per_page",
        retention_bounded=True,
    ),
    # --- Org-level endpoints with bespoke payload reshaping ---
    "sessions": SentryEndpointConfig(
        name="sessions",
        path="/organizations/{organization_slug}/sessions/",
        incremental_fields=INTERVAL_START_INCREMENTAL_FIELD,
        default_incremental_field="interval_start",
        partition_key="interval_start",
        primary_key=["interval_start", "project", "release", "environment", "session_status"],
        custom_iterator=True,
        retention_bounded=True,
    ),
    "organization_stats": SentryEndpointConfig(
        name="organization_stats",
        path="/organizations/{organization_slug}/stats_v2/",
        incremental_fields=INTERVAL_START_INCREMENTAL_FIELD,
        default_incremental_field="interval_start",
        partition_key="interval_start",
        primary_key=["interval_start", "outcome", "category", "reason"],
        custom_iterator=True,
        retention_bounded=True,
    ),
    "organization_stats_summary": SentryEndpointConfig(
        name="organization_stats_summary",
        path="/organizations/{organization_slug}/stats-summary/",
        incremental_fields=[],
        primary_key=["project_id", "category"],
        custom_iterator=True,
    ),
    "trace_item_attributes": SentryEndpointConfig(
        name="trace_item_attributes",
        path="/organizations/{organization_slug}/trace-items/attributes/",
        incremental_fields=[],
        primary_key=["dataset", "key", "attribute_type"],
        custom_iterator=True,
    ),
    "trace_item_stats": SentryEndpointConfig(
        name="trace_item_stats",
        path="/organizations/{organization_slug}/trace-items/stats/",
        incremental_fields=[],
        primary_key=["item_type", "attribute", "label"],
        custom_iterator=True,
    ),
    "project_ownership": SentryEndpointConfig(
        name="project_ownership",
        path="/projects/{organization_slug}/{project_slug}/ownership/",
        incremental_fields=[],
        primary_key=["project_id"],
        custom_iterator=True,
    ),
    "project_stats": SentryEndpointConfig(
        name="project_stats",
        path="/projects/{organization_slug}/{project_slug}/stats/",
        incremental_fields=EPOCH_TIMESTAMP_INCREMENTAL_FIELD,
        default_incremental_field="timestamp",
        primary_key=["project_id", "stat", "timestamp"],
        custom_iterator=True,
        retention_bounded=True,
    ),
    # --- Parent/child fan-out endpoints ---
    "release_deploys": SentryEndpointConfig(
        name="release_deploys",
        path="/organizations/{organization_slug}/releases/{version}/deploys/",
        incremental_fields=[],
        partition_key="date_started",
        primary_key=["release_version", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="releases",
            resolve_param="version",
            resolve_field="version",
            include_from_parent=["version"],
            parent_field_renames={"version": "release_version"},
        ),
    ),
    "release_commits": SentryEndpointConfig(
        name="release_commits",
        path="/organizations/{organization_slug}/releases/{version}/commits/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key=["release_version", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="releases",
            resolve_param="version",
            resolve_field="version",
            include_from_parent=["version"],
            parent_field_renames={"version": "release_version"},
        ),
    ),
    "repo_commits": SentryEndpointConfig(
        name="repo_commits",
        path="/organizations/{organization_slug}/repos/{repo_id}/commits/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key=["repo_id", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="repos",
            resolve_param="repo_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "repo_id"},
        ),
    ),
    "monitor_checkins": SentryEndpointConfig(
        name="monitor_checkins",
        path="/organizations/{organization_slug}/monitors/{monitor_id_or_slug}/checkins/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key=["monitor_id", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="monitors",
            resolve_param="monitor_id_or_slug",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "monitor_id"},
        ),
    ),
    "project_user_feedback": SentryEndpointConfig(
        name="project_user_feedback",
        path="/projects/{organization_slug}/{project_slug}/user-feedback/",
        incremental_fields=[],
        partition_key="date_created",
        primary_key=["project_id", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
    "project_filters": SentryEndpointConfig(
        name="project_filters",
        path="/projects/{organization_slug}/{project_slug}/filters/",
        incremental_fields=[],
        primary_key=["project_id", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="project_slug",
            resolve_field="slug",
            include_from_parent=["id", "slug"],
            parent_field_renames={"id": "project_id", "slug": "project_slug"},
        ),
    ),
}

ENDPOINTS = tuple(SENTRY_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SENTRY_ENDPOINTS.items()
}
