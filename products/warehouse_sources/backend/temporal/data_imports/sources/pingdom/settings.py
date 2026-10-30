from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DAY_SECONDS = 24 * 60 * 60

# Every per-check child is fetched from the check listing. A check deleted between the listing and
# its child request 404s, which must not fail the rest of the fan-out.
CHECK_FANOUT = DependentEndpointConfig(
    parent_name="checks",
    resolve_param="checkid",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "checkid"},
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)


@dataclass(frozen=True)
class PingdomEndpointConfig:
    name: str
    path: str
    # Dotted path to the list of rows in the response body (e.g. "actions.alerts"
    # for the nested {"actions": {"alerts": [...]}} wrapper).
    data_key: str
    # Alerts have no unique id, so the primary key can be composite.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning.
    partition_key: Optional[str] = None
    # Max page size the endpoint accepts (checks allow 25000, actions 1000).
    page_size: int = 1000
    # Per-check endpoints only take a `from`/`to` time window and are fanned out over /checks.
    fanout: Optional[DependentEndpointConfig] = None
    paginated: bool = True
    # Pagination stops before an offset the endpoint rejects (/results caps it at 43200).
    maximum_offset: Optional[int] = None
    params: dict[str, Any] = field(default_factory=dict)
    # Windowed endpoints: how far back a full refresh or a first incremental sync reads, and the
    # widest `from`/`to` span one request may ask for. Longer ranges are split into windows.
    lookback_seconds: Optional[int] = None
    max_window_seconds: Optional[int] = None

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


# Pingdom API 3.1 timestamps are UNIX epoch seconds. /actions and the per-check endpoints expose a
# server-side `from`/`to` time filter; /checks, /probes, /maintenance and /tms/check are small
# full-refresh dimension tables.
PINGDOM_ENDPOINTS: dict[str, PingdomEndpointConfig] = {
    "checks": PingdomEndpointConfig(
        name="checks",
        path="/checks",
        data_key="checks",
        page_size=25000,
    ),
    "probes": PingdomEndpointConfig(
        name="probes",
        path="/probes",
        data_key="probes",
    ),
    "maintenance": PingdomEndpointConfig(
        name="maintenance",
        path="/maintenance",
        data_key="maintenance",
    ),
    "alerts": PingdomEndpointConfig(
        name="alerts",
        path="/actions",
        data_key="actions.alerts",
        # Alert rows carry no id; (checkid, time, userid, via) is the closest natural key and can
        # still collide — an expected trait of this data, not something the user can fix. The
        # merge's own per-batch dedup (keep-last-per-key) resolves the collision safely, so
        # incremental syncing (via `time` below) stays available.
        primary_keys=["checkid", "time", "userid", "via"],
        partition_key="time",
        page_size=1000,
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "transaction_checks": PingdomEndpointConfig(
        name="transaction_checks",
        path="/tms/check",
        data_key="checks",
        partition_key="created_at",
    ),
    "results": PingdomEndpointConfig(
        name="results",
        path="/results/{checkid}",
        data_key="results",
        fanout=CHECK_FANOUT,
        primary_keys=["checkid", "probeid", "time"],
        partition_key="time",
        page_size=1000,
        maximum_offset=43200,
        # A one-minute check writes ~1440 raw results a day, so a 7-day window stays under the offset cap.
        lookback_seconds=7 * DAY_SECONDS,
        max_window_seconds=7 * DAY_SECONDS,
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    # The states cover the whole requested window, so the first one is clipped to `from` and the
    # last one is still open. A `from` taken from the global watermark would clip a different state
    # per check, so this table is full refresh only.
    "outages": PingdomEndpointConfig(
        name="outages",
        path="/summary.outage/{checkid}",
        data_key="summary.states",
        fanout=CHECK_FANOUT,
        primary_keys=["checkid", "timefrom"],
        partition_key="timefrom",
        paginated=False,
        params={"order": "asc"},
        lookback_seconds=365 * DAY_SECONDS,
    ),
    "performance": PingdomEndpointConfig(
        name="performance",
        path="/summary.performance/{checkid}",
        data_key="summary.hours",
        fanout=CHECK_FANOUT,
        primary_keys=["checkid", "starttime"],
        partition_key="starttime",
        paginated=False,
        params={"resolution": "hour", "includeuptime": "true", "order": "asc"},
        # Pingdom limits hourly report windows to about one week per request.
        lookback_seconds=7 * DAY_SECONDS,
        max_window_seconds=7 * DAY_SECONDS,
        incremental_fields=[
            {
                "label": "starttime",
                "type": IncrementalFieldType.DateTime,
                "field": "starttime",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
}

ENDPOINTS = tuple(PINGDOM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PINGDOM_ENDPOINTS.items() if config.incremental_fields
}
