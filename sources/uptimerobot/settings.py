from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# UptimeRobot v2 caps `limit` at 50 on every paginated list endpoint.
PAGE_LIMIT = 50

# UptimeRobot rejects response-time windows wider than 7 days, so history is walked in 7-day chunks.
RESPONSE_TIMES_WINDOW_DAYS = 7
# First response_times sync walks back this far. Free plans only retain recent response times, so a
# deeper backfill would mostly fetch empty windows; merge dedupes any overlap on later runs.
RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS = 30


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


@dataclass
class UptimeRobotEndpointConfig:
    name: str
    # v2 API method (e.g. "getMonitors"). Every v2 call is a form-encoded POST with the api_key in
    # the body — there are no plain GET endpoints.
    method: str
    # Key in the response JSON holding the row list ("monitors", "alert_contacts", "mwindows", "psps").
    response_key: str
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
}

ENDPOINTS = tuple(UPTIMEROBOT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in UPTIMEROBOT_ENDPOINTS.items()
}
