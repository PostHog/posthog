from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class PylonEndpointConfig:
    name: str
    path: str
    # Most list endpoints return the records under `data` with a `pagination` object; macros and a
    # handful of reference endpoints return a single un-paginated `data` array. We follow the
    # `pagination.has_next_page`/`cursor` contract whenever the API returns one, so this is purely a
    # documentation hint and never gates the loop.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-style field used for datetime partitioning. None for endpoints whose objects
    # expose no stable timestamp (contacts, users, teams, tags, ...).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only issues exposes a genuine server-side time filter (start_time/end_time), so it is the only
    # endpoint that can sync incrementally. Everything else is cursor-only and ships full refresh.
    supports_incremental: bool = False
    # `GET /issues` requires an RFC3339 start_time/end_time window capped at 30 days, so its backfill
    # is walked forward one <=30-day window at a time rather than as a single cursor scroll.
    windowed: bool = False
    # First-sync lookback for windowed endpoints (issues). Issues older than this aren't pulled on the
    # initial load, matching how other high-volume event-style endpoints bound their first sync.
    default_lookback_days: Optional[int] = None
    # Page size to request. `GET /accounts` *requires* `limit`; issues accepts up to 20000. We send a
    # conservative value everywhere to bound peak memory while keeping request counts low under the
    # per-endpoint rate limits.
    limit: Optional[int] = None
    # custom-fields requires an `object_type` query param and has no single "all" value, so we fan out
    # over each object type and stamp it onto every row. The id is only unique within an object type,
    # hence the composite primary key.
    fan_out_object_types: Optional[list[str]] = None
    should_sync_default: bool = True


# Pylon caps `/issues` time windows at 30 days.
ISSUES_MAX_WINDOW_DAYS = 30

# object_type values accepted by `GET /custom-fields` (per the API reference). We fan out over all of
# them so a single `custom_fields` table covers every custom field definition in the workspace.
CUSTOM_FIELD_OBJECT_TYPES = ["account", "issue", "contact", "task", "project", "meeting", "opportunity"]


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


PYLON_ENDPOINTS: dict[str, PylonEndpointConfig] = {
    "issues": PylonEndpointConfig(
        name="issues",
        path="/issues",
        partition_key="created_at",
        supports_incremental=True,
        windowed=True,
        default_lookback_days=365,
        limit=2000,
        # The /issues time window is required but the docs don't state which timestamp it filters on.
        # We assume `created_at` (stable, also our partition key) and always extend the window up to
        # "now", so even if the server actually filters on activity time the windowed backfill still
        # covers the full history and merge dedupes on `id`. See pylon.py for the windowing logic.
        incremental_fields=[_datetime_field("created_at")],
    ),
    "accounts": PylonEndpointConfig(
        name="accounts",
        path="/accounts",
        partition_key="created_at",
        limit=999,  # accounts requires limit and rejects values >= 1000
    ),
    "contacts": PylonEndpointConfig(
        name="contacts",
        path="/contacts",
        limit=999,
    ),
    "users": PylonEndpointConfig(
        name="users",
        path="/users",
    ),
    "teams": PylonEndpointConfig(
        name="teams",
        path="/teams",
    ),
    "tags": PylonEndpointConfig(
        name="tags",
        path="/tags",
    ),
    "custom_fields": PylonEndpointConfig(
        name="custom_fields",
        path="/custom-fields",
        primary_keys=["object_type", "id"],
        fan_out_object_types=CUSTOM_FIELD_OBJECT_TYPES,
    ),
    "ticket_forms": PylonEndpointConfig(
        name="ticket_forms",
        path="/ticket-forms",
    ),
    "user_roles": PylonEndpointConfig(
        name="user_roles",
        path="/user-roles",
    ),
    "macros": PylonEndpointConfig(
        name="macros",
        path="/macros",
        partition_key="created_at",
    ),
    "knowledge_bases": PylonEndpointConfig(
        name="knowledge_bases",
        path="/knowledge-bases",
    ),
    "tasks": PylonEndpointConfig(
        name="tasks",
        path="/tasks",
        partition_key="created_at",
        limit=999,
    ),
    "issue_statuses": PylonEndpointConfig(
        name="issue_statuses",
        path="/issue-statuses",
        # IssueStatus objects have no `id`; `slug` is the stable unique key.
        primary_keys=["slug"],
    ),
}

ENDPOINTS = tuple(PYLON_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PYLON_ENDPOINTS.items()
}
