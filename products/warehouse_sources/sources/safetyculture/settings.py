from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


def _modified_at_incremental_fields() -> list[IncrementalField]:
    # SafetyCulture's only server-side time filter is `modified_after`, which keys off `modified_at`.
    # Advertising just `modified_at` keeps the user's chosen cursor aligned with what the API filters on.
    return [
        {
            "label": "modified_at",
            "type": IncrementalFieldType.DateTime,
            "field": "modified_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


def _due_time_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "due_time",
            "type": IncrementalFieldType.DateTime,
            "field": "due_time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass(frozen=True)
class SafetyCultureEndpointConfig:
    name: str
    path: str  # Path under https://api.safetyculture.io, e.g. "/feed/inspections"
    # The feed documents a `modified_after` query param that filters server-side on `modified_at`.
    supports_incremental: bool
    # Static query params sent on the first request only — every later page comes from the verbatim
    # `metadata.next_page` path, which already carries them.
    params: dict[str, str] = field(default_factory=dict)
    # Stable creation-time field to partition by. None when the feed exposes no created_at.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Every data feed row carries a feed-unique `id` (e.g. inspection_items' `id` is the combined
    # inspection item ID, distinct from the per-template `item_id`).
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Non-empty marks a POST search endpoint scoped to one structure type per request; the sync
    # walks each listed type in turn.
    structure_types: tuple[str, ...] = ()
    # Query param that carries the incremental watermark on the first request.
    incremental_param: str = "modified_after"
    # How far before the watermark an incremental sync starts reading, for a feed whose filter
    # field can sit ahead of the rows that still change.
    incremental_rewind: Optional[timedelta] = None
    sort_mode: Optional[Literal["asc"]] = "asc"
    # Primary key fields the feed omits on some rows. They are set to "" so a merge can match them.
    blank_when_missing: tuple[str, ...] = ()


# SafetyCulture Data Feed endpoints (https://developer.safetyculture.com/reference/data-feeds) —
# the bulk-extraction API SafetyCulture recommends for warehouse syncs. Every feed returns
# {"metadata": {"next_page", "remaining_records"}, "data": [...]}; the `next_page` path must be
# followed verbatim. `archived`/`completed` are passed as "both" so the warehouse holds everything
# and users filter on the corresponding columns instead.
SAFETYCULTURE_ENDPOINTS: dict[str, SafetyCultureEndpointConfig] = {
    "inspections": SafetyCultureEndpointConfig(
        name="inspections",
        path="/feed/inspections",
        supports_incremental=True,
        params={"archived": "both", "completed": "both"},
        incremental_fields=_modified_at_incremental_fields(),
    ),
    "inspection_items": SafetyCultureEndpointConfig(
        name="inspection_items",
        path="/feed/inspection_items",
        supports_incremental=True,
        params={"archived": "both", "completed": "both"},
        incremental_fields=_modified_at_incremental_fields(),
    ),
    "templates": SafetyCultureEndpointConfig(
        name="templates",
        path="/feed/templates",
        supports_incremental=True,
        params={"archived": "both"},
        incremental_fields=_modified_at_incremental_fields(),
    ),
    "actions": SafetyCultureEndpointConfig(
        name="actions",
        path="/feed/actions",
        supports_incremental=True,
        incremental_fields=_modified_at_incremental_fields(),
    ),
    "issues": SafetyCultureEndpointConfig(
        name="issues",
        path="/feed/issues",
        # The issues feed documents no `modified_after` param, so it's full refresh only.
        supports_incremental=False,
    ),
    "assets": SafetyCultureEndpointConfig(
        name="assets",
        path="/feed/assets",
        supports_incremental=False,
    ),
    "users": SafetyCultureEndpointConfig(
        name="users",
        path="/feed/users",
        supports_incremental=False,
    ),
    "groups": SafetyCultureEndpointConfig(
        name="groups",
        path="/feed/groups",
        supports_incremental=False,
        partition_key=None,
    ),
    "sites": SafetyCultureEndpointConfig(
        name="sites",
        path="/feed/sites",
        supports_incremental=False,
        partition_key=None,
    ),
    # Structures API (https://developer.safetyculture.com/reference/structuresservice_searchstructures).
    # Only the built-in site and group types can be enumerated: org-defined structure types have no
    # public listing endpoint. There is no time filter, so it's full refresh only.
    "structures": SafetyCultureEndpointConfig(
        name="structures",
        path="/structures/v1/structures/search",
        supports_incremental=False,
        primary_keys=["structure_uuid"],
        structure_types=("SYSTEM_STRUCTURE_TYPE_SITE", "SYSTEM_STRUCTURE_TYPE_GROUP"),
    ),
    "schedules": SafetyCultureEndpointConfig(
        name="schedules",
        path="/feed/schedules",
        supports_incremental=False,
        # The schedules feed exposes `modified_at` but no `created_at`, so there is no stable
        # partition key.
        partition_key=None,
    ),
    # Membership and assignee join feeds. None exposes `created_at`, and a full refresh is the only
    # way to drop a removed membership or assignment, so they all sync full refresh.
    "group_users": SafetyCultureEndpointConfig(
        name="group_users",
        path="/feed/group_users",
        supports_incremental=False,
        partition_key=None,
        primary_keys=["group_id", "user_id"],
    ),
    "site_members": SafetyCultureEndpointConfig(
        name="site_members",
        path="/feed/site_members",
        supports_incremental=False,
        partition_key=None,
        primary_keys=["site_id", "member_id"],
    ),
    "action_assignees": SafetyCultureEndpointConfig(
        name="action_assignees",
        path="/feed/action_assignees",
        # The feed accepts `modified_after` (on the parent action), but its rows carry no
        # `modified_at` to hold the watermark.
        supports_incremental=False,
        partition_key=None,
    ),
    "issue_assignees": SafetyCultureEndpointConfig(
        name="issue_assignees",
        path="/feed/issue_assignees",
        # The issue assignees feed documents no `modified_after` param, so it's full refresh only.
        supports_incremental=False,
        partition_key=None,
    ),
    # Scheduling service feed, which replaces the legacy /feed/schedule_occurrences. Records are one
    # per occurrence, assignee and site or asset. `start_date` filters on `due_time`, and the
    # default window is now - 5 months to now + 1 month. A full refresh holds only that window, so
    # incremental merge is the way to keep older occurrences.
    "schedule_occurrences": SafetyCultureEndpointConfig(
        name="schedule_occurrences",
        path="/scheduling/v1/feed/schedule_occurrences",
        supports_incremental=True,
        params={"limit": "1000"},
        # `due_time` is part of the occurrence `id`, so it never changes.
        partition_key="due_time",
        incremental_fields=_due_time_incremental_fields(),
        primary_keys=["id", "target_id"],
        incremental_param="start_date",
        # The watermark is the latest due time, up to a month ahead of the last sync. An occurrence
        # keeps changing status until its due time, so re-read everything due since the last sync.
        incremental_rewind=timedelta(days=45),
        # The feed documents no row order.
        sort_mode=None,
        blank_when_missing=("target_id",),
    ),
    # Timeline feeds: `modified_after` filters on the parent action, and the rows carry only their
    # creation `timestamp`, so there is no watermark column. Full refresh only.
    "action_timeline_items": SafetyCultureEndpointConfig(
        name="action_timeline_items",
        path="/feed/action_timeline_items",
        supports_incremental=False,
        partition_key="timestamp",
    ),
    "issue_timeline_items": SafetyCultureEndpointConfig(
        name="issue_timeline_items",
        path="/feed/issue_timeline_items",
        supports_incremental=False,
        partition_key="timestamp",
    ),
    # Training feed: one row per user and course, in camelCase. `modifiedAfter` exists, but the rows
    # have no modified time to hold the watermark, so it's full refresh only.
    "training_course_progress": SafetyCultureEndpointConfig(
        name="training_course_progress",
        path="/training/v1/feed/training-course-progress",
        supports_incremental=False,
        params={"completionStatus": "COMPLETION_STATUS_ALL"},
        partition_key=None,
        primary_keys=["courseId", "userId"],
    ),
}

ENDPOINTS = tuple(SAFETYCULTURE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SAFETYCULTURE_ENDPOINTS.items()
}
