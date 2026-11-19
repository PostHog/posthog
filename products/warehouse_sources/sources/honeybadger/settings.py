from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class HoneybadgerEndpointConfig:
    name: str
    # Path template under the v2 base URL; `{project_id}` / `{fault_id}` / `{site_id}` / `{team_id}` /
    # `{account_id}` are filled in by the fan-out.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Incremental field name -> query param that server-side filters on it.
    incremental_params: dict[str, str] = field(default_factory=dict)
    incremental_param_format: Literal["unix", "iso8601"] = "unix"
    default_incremental_field: str | None = None
    # Incremental field name -> query param on the fan-out parent list that the watermark also bounds.
    parent_incremental_params: dict[str, str] = field(default_factory=dict)
    # Fan-out parent field -> column injected into each child row.
    parent_fields: dict[str, str] = field(default_factory=dict)
    partition_key: str | None = None  # Stable creation-time field; never a mutating timestamp
    # Two-level fan-out: projects -> {parent} -> {endpoint}
    fan_out_parent: Literal["faults", "sites", "alarms"] | None = None
    # One-level fan-out over a list that isn't scoped to a project: {parent} -> {endpoint}
    root_fan_out_parent: Literal["teams", "accounts"] | None = None
    # False for endpoints that return a bare JSON array with no `limit` / `links.next` paging.
    paginated: bool = True
    # Key of the row array in a wrapped response.
    data_selector: str = "results"
    # Response is `[key, count]` pairs instead of objects; the key lands in `pair_key`.
    time_series: bool = False
    pair_key: str = "bucket_start"
    pair_key_format: Literal["epoch", "iso8601", "text"] = "epoch"
    # Report endpoints take an ISO 8601 `start`; send one this many days back so the window is explicit.
    report_window_days: int | None = None
    query_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True


_created_at_field: IncrementalField = {
    "label": "created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at",
    "field_type": IncrementalFieldType.DateTime,
}

HONEYBADGER_ENDPOINTS: dict[str, HoneybadgerEndpointConfig] = {
    "projects": HoneybadgerEndpointConfig(
        name="projects",
        path="/projects",
        # The projects list has no server-side timestamp filter, so it's full refresh only.
        incremental_fields=[],
    ),
    "faults": HoneybadgerEndpointConfig(
        name="faults",
        path="/projects/{project_id}/faults",
        # Fault ids look globally unique, but the API doesn't document that — include the
        # parent project id so the key is unique table-wide across the fan-out.
        primary_keys=["project_id", "id"],
        incremental_fields=[
            _created_at_field,
            {
                "label": "last_notice_at",
                "type": IncrementalFieldType.DateTime,
                "field": "last_notice_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        # `created_after` only picks up new faults; `occurred_after` (filters on the fault's
        # last notice) also re-pulls existing faults that reoccurred, keeping counts fresh.
        incremental_params={"created_at": "created_after", "last_notice_at": "occurred_after"},
        default_incremental_field="last_notice_at",
        partition_key="created_at",
    ),
    "notices": HoneybadgerEndpointConfig(
        name="notices",
        path="/projects/{project_id}/faults/{fault_id}/notices",
        # Notice ids are UUIDs.
        primary_keys=["id"],
        incremental_fields=[_created_at_field],
        incremental_params={"created_at": "created_after"},
        default_incremental_field="created_at",
        parent_incremental_params={"created_at": "occurred_after"},
        partition_key="created_at",
        fan_out_parent="faults",
        # One request per fault minimum against a 360 req/hour quota — opt-in only.
        should_sync_default=False,
    ),
    "deploys": HoneybadgerEndpointConfig(
        name="deploys",
        path="/projects/{project_id}/deploys",
        primary_keys=["project_id", "id"],
        incremental_fields=[_created_at_field],
        incremental_params={"created_at": "created_after"},
        default_incremental_field="created_at",
        partition_key="created_at",
    ),
    "sites": HoneybadgerEndpointConfig(
        name="sites",
        path="/projects/{project_id}/sites",
        # Site ids are UUIDs; keep the parent project id in the key anyway for consistency.
        primary_keys=["project_id", "id"],
        # The sites (uptime checks) list has no server-side timestamp filter.
        incremental_fields=[],
    ),
    "environments": HoneybadgerEndpointConfig(
        name="environments",
        path="/projects/{project_id}/environments",
        primary_keys=["project_id", "id"],
        incremental_fields=[],
        partition_key="created_at",
    ),
    "occurrences": HoneybadgerEndpointConfig(
        name="occurrences",
        path="/projects/{project_id}/occurrences",
        primary_keys=["project_id", "bucket_start"],
        # The API only serves a rolling window of buckets with no time filter; `month` returns
        # the most recent month in one-day buckets.
        incremental_fields=[],
        partition_key="bucket_start",
        paginated=False,
        time_series=True,
        query_params={"period": "month"},
    ),
    "affected_users": HoneybadgerEndpointConfig(
        name="affected_users",
        path="/projects/{project_id}/faults/{fault_id}/affected_users",
        primary_keys=["project_id", "fault_id", "user"],
        # The endpoint has no time filter, but a fault's affected users only change when it gets
        # a new notice, so the fault's last notice time bounds the fault enumeration instead.
        incremental_fields=[
            {
                "label": "fault_last_notice_at",
                "type": IncrementalFieldType.DateTime,
                "field": "fault_last_notice_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        default_incremental_field="fault_last_notice_at",
        parent_incremental_params={"fault_last_notice_at": "occurred_after"},
        parent_fields={"last_notice_at": "fault_last_notice_at"},
        fan_out_parent="faults",
        paginated=False,
        # One request per fault against a 360 req/hour quota — opt-in only.
        should_sync_default=False,
    ),
    "outages": HoneybadgerEndpointConfig(
        name="outages",
        path="/projects/{project_id}/sites/{site_id}/outages",
        # Outages have no id of their own.
        primary_keys=["project_id", "site_id", "created_at"],
        incremental_fields=[_created_at_field],
        incremental_params={"created_at": "created_after"},
        default_incremental_field="created_at",
        partition_key="created_at",
        fan_out_parent="sites",
    ),
    "uptime_checks": HoneybadgerEndpointConfig(
        name="uptime_checks",
        path="/projects/{project_id}/sites/{site_id}/uptime_checks",
        # Individual check results have no id; a site is checked once per location per run.
        primary_keys=["project_id", "site_id", "created_at", "location"],
        incremental_fields=[_created_at_field],
        incremental_params={"created_at": "created_after"},
        default_incremental_field="created_at",
        partition_key="created_at",
        fan_out_parent="sites",
        # A site checked every minute from every location produces thousands of rows a day,
        # 25 per request against a 360 req/hour quota — opt-in only.
        should_sync_default=False,
    ),
    "comments": HoneybadgerEndpointConfig(
        name="comments",
        path="/projects/{project_id}/faults/{fault_id}/comments",
        primary_keys=["project_id", "fault_id", "id"],
        # The comments list has no server-side timestamp filter, and new comments don't move the
        # fault's last notice time, so neither the child nor the fault listing can be bounded.
        incremental_fields=[],
        partition_key="created_at",
        fan_out_parent="faults",
        # One request per fault against a 360 req/hour quota — opt-in only.
        should_sync_default=False,
    ),
    "check_ins": HoneybadgerEndpointConfig(
        name="check_ins",
        path="/projects/{project_id}/check_ins",
        primary_keys=["project_id", "id"],
        # Check-ins are monitor definitions plus current state, with no timestamp filter.
        incremental_fields=[],
    ),
    "alarm_history": HoneybadgerEndpointConfig(
        name="alarm_history",
        path="/projects/{project_id}/alarms/{alarm_id}/history",
        primary_keys=["project_id", "alarm_id", "id"],
        # The history list has no server-side timestamp filter.
        incremental_fields=[],
        partition_key="created_at",
        fan_out_parent="alarms",
        data_selector="triggers",
        # Alarms are part of Honeybadger Insights, which not every account uses — opt-in only.
        should_sync_default=False,
    ),
    "notices_per_day": HoneybadgerEndpointConfig(
        name="notices_per_day",
        path="/projects/{project_id}/reports/notices_per_day",
        primary_keys=["project_id", "day"],
        # `start` filters the report server-side. The watermark is the last day already synced,
        # so that (still growing) day is pulled again and merged on the primary key.
        incremental_fields=[
            {
                "label": "day",
                "type": IncrementalFieldType.DateTime,
                "field": "day",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        incremental_params={"day": "start"},
        incremental_param_format="iso8601",
        default_incremental_field="day",
        partition_key="day",
        paginated=False,
        time_series=True,
        pair_key="day",
        pair_key_format="iso8601",
        report_window_days=30,
    ),
    "notices_by_class": HoneybadgerEndpointConfig(
        name="notices_by_class",
        path="/projects/{project_id}/reports/notices_by_class",
        primary_keys=["project_id", "klass"],
        # Counts over a rolling window, so each sync replaces the table.
        incremental_fields=[],
        paginated=False,
        time_series=True,
        pair_key="klass",
        pair_key_format="text",
        report_window_days=30,
    ),
    "accounts": HoneybadgerEndpointConfig(
        name="accounts",
        path="/accounts",
        # The accounts list has no server-side timestamp filter.
        incremental_fields=[],
        paginated=False,
    ),
    "account_users": HoneybadgerEndpointConfig(
        name="account_users",
        path="/accounts/{account_id}/users",
        primary_keys=["account_id", "id"],
        incremental_fields=[],
        parent_fields={"name": "account_name"},
        root_fan_out_parent="accounts",
        paginated=False,
        # Listing account users can need an admin role on the account — opt-in only.
        should_sync_default=False,
    ),
    "team_members": HoneybadgerEndpointConfig(
        name="team_members",
        path="/teams/{team_id}/team_members",
        primary_keys=["team_id", "id"],
        incremental_fields=[],
        parent_fields={"name": "team_name"},
        root_fan_out_parent="teams",
        paginated=False,
        # Listing team members can need an admin role on the team — opt-in only.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(HONEYBADGER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HONEYBADGER_ENDPOINTS.items()
}
