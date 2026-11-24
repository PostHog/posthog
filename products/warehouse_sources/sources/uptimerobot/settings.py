from dataclasses import field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

# UptimeRobot v2 caps `limit` at 50 on every paginated list endpoint.
PAGE_LIMIT = 50
# v3 list endpoints that take `limit` cap it at 200.
V3_PAGE_LIMIT = 200

# UptimeRobot rejects response-time windows wider than 7 days, so history is walked in 7-day chunks.
RESPONSE_TIMES_WINDOW_DAYS = 7
# First response_times sync walks back this far. Free plans only retain recent response times, so a
# deeper backfill would mostly fetch empty windows; merge dedupes any overlap on later runs.
RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS = 30
# First monitor_daily_uptime sync (and every full refresh) covers this many finished days. Each day is
# one request per monitor, so a deeper backfill multiplies the request count.
DAILY_UPTIME_INITIAL_LOOKBACK_DAYS = 30


def _datetime_incremental_fields() -> list[IncrementalField]:
    # UptimeRobot timestamps are Unix epoch seconds (integers) named `datetime`.
    return [
        {
            "label": "datetime",
            "type": IncrementalFieldType.DateTime,
            "field": "datetime",
            "field_type": IncrementalFieldType.Integer,
        },
    ]


def _iso_datetime_incremental_fields(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


@frozen
class UptimeRobotFanOut:
    # v3 list endpoint of the parent rows (e.g. "/incidents"). Paged with `limit` and a cursor.
    parent_path: str
    # Column the parent's `id` is written to on each child row.
    parent_key: str
    # Child rows come from one request per parent per UTC day instead of a cursor-paged list.
    daily_windows: bool = False
    # Incremental runs only revisit parents whose `resolvedAt` is empty or after the watermark.
    skip_resolved_parents: bool = False


@frozen
class UptimeRobotEndpointConfig:
    name: str
    # v2 API method (e.g. "getMonitors"). Every v2 call is a form-encoded POST with the api_key in
    # the body — there are no plain GET endpoints. For v3 endpoints this is the REST path (e.g. "/tags").
    method: str
    # Key in the response JSON holding the row list ("monitors", "alert_contacts", "mwindows", "psps").
    response_key: str
    # Some tables only exist on the v3 REST API: a bearer-authenticated GET with cursor pagination.
    api_version: Literal["v2", "v3"] = "v2"
    # v3 only: whether the endpoint accepts a `limit` page-size param.
    v3_accepts_limit: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime-ish field to partition by (Unix epoch int). None disables partitioning.
    partition_key: Optional[str] = None
    partition_format: Literal["month", "week", "day"] = "month"
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Extra form params sent on every request for this endpoint.
    extra_params: dict[str, str | int] = field(default_factory=dict)
    # Fan-out endpoints materialize a nested per-monitor list ("logs" / "response_times") from
    # getMonitors as one row per entry, keyed back to the monitor id.
    monitor_list_key: Optional[Literal["logs", "response_times"]] = None
    # Redact the `value` of credential-bearing alert contacts (webhook/integration URLs and tokens).
    redact_alert_contact_values: bool = False
    # v3 only: the child endpoint is called once per parent row; `method` holds the path with `{id}`.
    fan_out: Optional[UptimeRobotFanOut] = None
    # Rows with no id get an `id` derived from the parent id and these fields.
    row_id_fields: tuple[str, ...] = ()
    # (value field, channel type field) of a recipient that can be a webhook URL or a token.
    recipient_fields: Optional[tuple[str, str]] = None


UPTIMEROBOT_ENDPOINTS: dict[str, UptimeRobotEndpointConfig] = {
    # Small table (one row per monitor) with mutable status/uptime-ratio fields and no server-side
    # updated-since filter — full refresh every run.
    "monitors": UptimeRobotEndpointConfig(
        name="monitors",
        method="getMonitors",
        response_key="monitors",
        partition_key="create_datetime",
        extra_params={
            # Adds `custom_uptime_ratio` (dash-separated 1/7/30/365-day ratios) and
            # `all_time_uptime_ratio` columns for SLA reporting.
            "custom_uptime_ratios": "1-7-30-365",
            "all_time_uptime_ratio": 1,
        },
    ),
    # Up/down/pause event log entries nested under each monitor. Entries are immutable and carry a
    # Unix `datetime`, which doubles as the incremental cursor and a stable partition key.
    "monitor_logs": UptimeRobotEndpointConfig(
        name="monitor_logs",
        method="getMonitors",
        response_key="monitors",
        monitor_list_key="logs",
        primary_keys=["monitor_id", "datetime", "type"],
        partition_key="datetime",
        supports_incremental=True,
        incremental_fields=_datetime_incremental_fields(),
        extra_params={"logs": 1},
    ),
    # Response-time samples nested under each monitor; immutable {datetime, value} pairs fetched in
    # 7-day windows. Higher volume than logs, so partition by week.
    "response_times": UptimeRobotEndpointConfig(
        name="response_times",
        method="getMonitors",
        response_key="monitors",
        monitor_list_key="response_times",
        primary_keys=["monitor_id", "datetime"],
        partition_key="datetime",
        partition_format="week",
        supports_incremental=True,
        incremental_fields=_datetime_incremental_fields(),
        extra_params={"response_times": 1},
    ),
    "alert_contacts": UptimeRobotEndpointConfig(
        name="alert_contacts",
        method="getAlertContacts",
        response_key="alert_contacts",
        redact_alert_contact_values=True,
    ),
    "maintenance_windows": UptimeRobotEndpointConfig(
        name="maintenance_windows",
        method="getMWindows",
        response_key="mwindows",
    ),
    "status_pages": UptimeRobotEndpointConfig(
        name="status_pages",
        method="getPSPs",
        response_key="psps",
    ),
    # Incidents change after they start (an open incident gets a resolvedAt and duration later), and
    # the only server-side filter is on startedAt, so an incremental sync would never pick up the
    # resolution. Full refresh every run.
    "incidents": UptimeRobotEndpointConfig(
        name="incidents",
        method="/incidents",
        response_key="data",
        api_version="v3",
        partition_key="startedAt",
    ),
    "monitor_groups": UptimeRobotEndpointConfig(
        name="monitor_groups",
        method="/monitor-groups",
        response_key="data",
        api_version="v3",
        v3_accepts_limit=True,
    ),
    "tags": UptimeRobotEndpointConfig(
        name="tags",
        method="/tags",
        response_key="data",
        api_version="v3",
        v3_accepts_limit=True,
    ),
    # One row per monitor per finished UTC day. A finished day never changes, so the date is a safe cursor.
    "monitor_daily_uptime": UptimeRobotEndpointConfig(
        name="monitor_daily_uptime",
        method="/monitors/{id}/stats/uptime",
        response_key="data",
        api_version="v3",
        fan_out=UptimeRobotFanOut(parent_path="/monitors", parent_key="monitor_id", daily_windows=True),
        primary_keys=["monitor_id", "date"],
        partition_key="date",
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
    ),
    # Sent alerts never change, but they arrive while an incident is open, so incremental runs revisit
    # only the incidents that are open or resolved after the watermark.
    "incident_alerts": UptimeRobotEndpointConfig(
        name="incident_alerts",
        method="/incidents/{id}/alerts",
        response_key="data",
        api_version="v3",
        v3_accepts_limit=True,
        fan_out=UptimeRobotFanOut(parent_path="/incidents", parent_key="incident_id", skip_resolved_parents=True),
        row_id_fields=("timestamp", "channelType", "recipientName", "recipientValue"),
        recipient_fields=("recipientValue", "channelType"),
        partition_key="timestamp",
        supports_incremental=True,
        incremental_fields=_iso_datetime_incremental_fields("timestamp"),
    ),
    "incident_activity_log": UptimeRobotEndpointConfig(
        name="incident_activity_log",
        method="/incidents/{id}/activity-log",
        response_key="data",
        api_version="v3",
        v3_accepts_limit=True,
        fan_out=UptimeRobotFanOut(parent_path="/incidents", parent_key="incident_id", skip_resolved_parents=True),
        # The delivery status of a notification can change, so it is not part of the id.
        row_id_fields=(
            "type",
            "date",
            "region",
            "incidentStatus",
            "alertLogType",
            "commentId",
            "sentToFullName",
            "sentToValue",
            "notificationType",
        ),
        recipient_fields=("sentToValue", "notificationType"),
        partition_key="date",
        supports_incremental=True,
        incremental_fields=_iso_datetime_incremental_fields("date"),
    ),
    # Announcements change status (pending, published, archived), and the API has no updated-since
    # filter, so full refresh every run.
    "status_page_announcements": UptimeRobotEndpointConfig(
        name="status_page_announcements",
        method="/psps/{id}/announcements",
        response_key="data",
        api_version="v3",
        v3_accepts_limit=True,
        fan_out=UptimeRobotFanOut(parent_path="/psps", parent_key="psp_id"),
        primary_keys=["psp_id", "id"],
    ),
}

ENDPOINTS = tuple(UPTIMEROBOT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in UPTIMEROBOT_ENDPOINTS.items()
}
