from dataclasses import field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen, incremental_field


@frozen
class ZoomEndpointConfig:
    name: str
    # Path template relative to the Zoom API base. Fan-out endpoints contain one placeholder
    # (``parent_param``) that is filled in per row of the ``parent`` endpoint.
    path: str
    # Key in the JSON response body that holds the list of records
    # (e.g. ``{"users": [...], "next_page_token": "..."}``).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A STABLE datetime field used for partitioning. Never use a field that
    # mutates over time (e.g. ``updated_at``) — partitions would be rewritten
    # on every sync.
    partition_key: Optional[str] = "created_at"
    # Name of the endpoint in ``ZOOM_ENDPOINTS`` whose rows fill the
    # path placeholder. Parents can chain, e.g. participants <- meeting instances <- meetings <- users.
    parent: Optional[str] = None
    parent_param: str = ""
    parent_field: str = "id"
    # Parent row fields copied onto each row, as parent field -> column name.
    parent_columns: dict[str, str] = field(default_factory=dict)
    # Static query params sent on every request to this endpoint.
    params: dict[str, str] = field(default_factory=dict)
    # Zoom caps ``page_size`` at 300 for these list endpoints.
    page_size: int = 300
    paginated: bool = True
    # Adds ``_uuid_path``: the row's ``uuid`` encoded the way Zoom requires in a path segment.
    adds_uuid_path: bool = False
    # Zoom caps the ``from``/``to`` range of these endpoints at one month, so they are read in
    # calendar-month windows by a custom iterator instead of the generic fan-out.
    monthly_windows: bool = False


# Zoom's meeting/webinar/user list endpoints expose no server-side timestamp filter, so they are
# full refresh. Only the report and recording endpoints take a ``from``/``to`` date range.
ZOOM_ENDPOINTS: dict[str, ZoomEndpointConfig] = {
    "users": ZoomEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        partition_key="created_at",
    ),
    "meetings": ZoomEndpointConfig(
        name="meetings",
        path="/users/{user_id}/meetings",
        data_key="meetings",
        partition_key="created_at",
        parent="users",
        parent_param="user_id",
        # ``scheduled`` returns all of a user's stored scheduled meetings,
        # including recurring ones — the most complete list for ingestion.
        params={"type": "scheduled"},
    ),
    "webinars": ZoomEndpointConfig(
        name="webinars",
        path="/users/{user_id}/webinars",
        data_key="webinars",
        partition_key="created_at",
        parent="users",
        parent_param="user_id",
    ),
    "meeting_registrants": ZoomEndpointConfig(
        name="meeting_registrants",
        path="/meetings/{meeting_id}/registrants",
        data_key="registrants",
        # Registrant IDs are only documented as unique within a meeting.
        primary_keys=["meeting_id", "id"],
        partition_key="create_time",
        parent="meetings",
        parent_param="meeting_id",
        parent_columns={"id": "meeting_id"},
    ),
    "webinar_registrants": ZoomEndpointConfig(
        name="webinar_registrants",
        path="/webinars/{webinar_id}/registrants",
        data_key="registrants",
        primary_keys=["webinar_id", "id"],
        partition_key="create_time",
        parent="webinars",
        parent_param="webinar_id",
        parent_columns={"id": "webinar_id"},
    ),
    # A meeting ID only resolves to its latest instance, so participants are read per ended
    # instance (UUID) instead.
    "meeting_instances": ZoomEndpointConfig(
        name="meeting_instances",
        path="/past_meetings/{meeting_id}/instances",
        data_key="meetings",
        primary_keys=["meeting_id", "uuid"],
        partition_key="start_time",
        parent="meetings",
        parent_param="meeting_id",
        parent_columns={"id": "meeting_id"},
        paginated=False,
        adds_uuid_path=True,
    ),
    "webinar_instances": ZoomEndpointConfig(
        name="webinar_instances",
        path="/past_webinars/{webinar_id}/instances",
        data_key="webinars",
        primary_keys=["webinar_id", "uuid"],
        partition_key="start_time",
        parent="webinars",
        parent_param="webinar_id",
        parent_columns={"id": "webinar_id"},
        paginated=False,
        adds_uuid_path=True,
    ),
    "meeting_participants": ZoomEndpointConfig(
        name="meeting_participants",
        path="/past_meetings/{meeting_uuid}/participants",
        data_key="participants",
        # A participant gets one row per join, so a rejoin shares the participant IDs.
        primary_keys=["meeting_uuid", "user_id", "join_time"],
        partition_key="join_time",
        parent="meeting_instances",
        parent_param="meeting_uuid",
        parent_field="_uuid_path",
        parent_columns={"meeting_id": "meeting_id", "uuid": "meeting_uuid"},
    ),
    "webinar_participants": ZoomEndpointConfig(
        name="webinar_participants",
        path="/past_webinars/{webinar_uuid}/participants",
        data_key="participants",
        primary_keys=["webinar_uuid", "user_id", "join_time"],
        partition_key="join_time",
        parent="webinar_instances",
        parent_param="webinar_uuid",
        parent_field="_uuid_path",
        parent_columns={"webinar_id": "webinar_id", "uuid": "webinar_uuid"},
    ),
    "groups": ZoomEndpointConfig(
        name="groups",
        path="/groups",
        data_key="groups",
        partition_key=None,
    ),
    "group_members": ZoomEndpointConfig(
        name="group_members",
        path="/groups/{group_id}/members",
        data_key="members",
        # A user can belong to several groups.
        primary_keys=["group_id", "id"],
        partition_key=None,
        parent="groups",
        parent_param="group_id",
        parent_columns={"id": "group_id"},
    ),
    "report_users": ZoomEndpointConfig(
        name="report_users",
        path="/report/users",
        data_key="users",
        # One row per host per month: the active hosts report plus the inactive hosts report.
        primary_keys=["period_start", "id"],
        partition_key="period_start",
        monthly_windows=True,
    ),
    "recordings": ZoomEndpointConfig(
        name="recordings",
        path="/users/{user_id}/recordings",
        data_key="meetings",
        # One row per meeting or webinar instance that has cloud recordings.
        primary_keys=["uuid"],
        partition_key="start_time",
        parent="users",
        parent_param="user_id",
        monthly_windows=True,
    ),
}

ENDPOINTS = tuple(ZOOM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "report_users": [incremental_field("period_start", IncrementalFieldType.Date)],
    "recordings": [incremental_field("start_time", IncrementalFieldType.DateTime)],
}

# Zoom lists a recording only after it finishes processing, which can be hours after the meeting
# starts, so incremental recording syncs re-read a trailing window.
RECORDINGS_INCREMENTAL_LOOKBACK_SECONDS = 3 * 24 * 60 * 60
