from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class StatusCakeEndpointConfig:
    name: str
    # Path template relative to the API base. Top-level endpoints are absolute (e.g. "/uptime");
    # per-test history endpoints carry a {test_id} placeholder filled in during fan-out.
    path: str
    # Unique across the whole table. Fan-out children include "test_id" (injected by the connector)
    # because a single sync aggregates rows from every test — the raw history rows carry no test id
    # and their timestamps are only unique within one test.
    primary_key: Optional[list[str]]
    # Name of the parent endpoint whose test ids this endpoint fans out over (None for top-level).
    fan_out_over: Optional[str] = None
    # Row field carrying the record's event time. Doubles as the incremental cursor (mapped to the
    # API's `after` UNIX-timestamp param) and the partition key — these timestamps are immutable
    # event times, never updated_at-style fields.
    timestamp_field: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    # Response fields dropped before rows are persisted. The warehouse is readable by any project
    # user, so a field carrying a live credential (e.g. a heartbeat push URL with its PK secret)
    # must never land there — otherwise it could be read back and used to spoof pings.
    scrub_fields: Optional[list[str]] = None


# StatusCake API v1 (https://developers.statuscake.com/api/). Config/test lists have no
# changed-since filter and are full refresh only; the per-test history endpoints accept
# `before`/`after` UNIX-timestamp bounds, which is what powers incremental sync.
STATUSCAKE_ENDPOINTS: dict[str, StatusCakeEndpointConfig] = {
    "uptime_tests": StatusCakeEndpointConfig(
        name="uptime_tests",
        path="/uptime",
        primary_key=["id"],
    ),
    "uptime_history": StatusCakeEndpointConfig(
        name="uptime_history",
        path="/uptime/{test_id}/history",
        # History rows have no id of their own; a test can be checked from more than one location,
        # so the location is part of the identity alongside the check timestamp.
        primary_key=["test_id", "created_at", "location"],
        fan_out_over="uptime_tests",
        timestamp_field="created_at",
        incremental_fields=[_datetime_field("created_at")],
    ),
    "uptime_periods": StatusCakeEndpointConfig(
        name="uptime_periods",
        path="/uptime/{test_id}/periods",
        primary_key=["test_id", "created_at"],
        fan_out_over="uptime_tests",
        timestamp_field="created_at",
        incremental_fields=[_datetime_field("created_at")],
    ),
    "uptime_alerts": StatusCakeEndpointConfig(
        name="uptime_alerts",
        path="/uptime/{test_id}/alerts",
        primary_key=["test_id", "triggered_at"],
        fan_out_over="uptime_tests",
        timestamp_field="triggered_at",
        incremental_fields=[_datetime_field("triggered_at")],
    ),
    "pagespeed_tests": StatusCakeEndpointConfig(
        name="pagespeed_tests",
        path="/pagespeed",
        primary_key=["id"],
    ),
    "pagespeed_history": StatusCakeEndpointConfig(
        name="pagespeed_history",
        path="/pagespeed/{test_id}/history",
        primary_key=["test_id", "created_at"],
        fan_out_over="pagespeed_tests",
        timestamp_field="created_at",
        incremental_fields=[_datetime_field("created_at")],
    ),
    "ssl_tests": StatusCakeEndpointConfig(
        name="ssl_tests",
        path="/ssl",
        primary_key=["id"],
    ),
    "heartbeat_tests": StatusCakeEndpointConfig(
        name="heartbeat_tests",
        path="/heartbeat",
        primary_key=["id"],
        # The push `url` embeds the check's PK credential; drop it so it never reaches the warehouse.
        scrub_fields=["url"],
    ),
    "contact_groups": StatusCakeEndpointConfig(
        name="contact_groups",
        path="/contact-groups",
        primary_key=["id"],
        # The `ping_url` callback is invoked when the group is alerted and commonly embeds a webhook
        # secret; drop it so it never reaches the warehouse and can't be read back to spoof alerts.
        scrub_fields=["ping_url"],
    ),
    "maintenance_windows": StatusCakeEndpointConfig(
        name="maintenance_windows",
        path="/maintenance-windows",
        primary_key=["id"],
    ),
    # Monitoring-location dimension. Locations carry no id, so the table is full-refresh replace
    # with no primary key (there is nothing to merge on).
    "uptime_locations": StatusCakeEndpointConfig(
        name="uptime_locations",
        path="/uptime-locations",
        primary_key=None,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(STATUSCAKE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STATUSCAKE_ENDPOINTS.items()
}
