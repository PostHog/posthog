from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Prefect Cloud caps `limit` on the /filter endpoints at 200 (the server's default API limit).
PAGE_LIMIT = 200

# Runs can change state (finish, fail, retry) after their start time has passed the watermark, so
# incremental syncs re-read a trailing day; merge dedupes the re-pulled rows on `id`.
RUN_LOOKBACK_SECONDS = 24 * 60 * 60


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class PrefectCloudEndpointConfig:
    name: str
    path: str  # POST path under the workspace base URL, e.g. "/flow_runs/filter"
    # Body key carrying the endpoint's own nested filter object (e.g. "flow_runs"). None when the
    # endpoint's filter model exposes no server-side time filter — those endpoints are full refresh.
    filter_key: Optional[str] = None
    # Advertised incremental cursor field -> the ascending sort enum the API accepts for it. Only
    # fields with BOTH a server-side `after_` filter and an ascending sort are advertised, so the
    # pipeline's asc watermark stays correct.
    incremental_sorts: dict[str, str] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Explicit stable sort for full-refresh paging — the API's implicit default is ID_DESC on run
    # endpoints, and offset pagination skips/dups rows without a stable order.
    sort: Optional[str] = None
    # Stable creation-time field to partition by. Only set on the high-volume run tables.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    default_incremental_lookback_seconds: Optional[int] = None
    should_sync_default: bool = True


PREFECT_CLOUD_ENDPOINTS: dict[str, PrefectCloudEndpointConfig] = {
    "flows": PrefectCloudEndpointConfig(
        name="flows",
        path="/flows/filter",
        # FlowFilter has no time-range filters (only id/name/tags), so full refresh only.
        sort="CREATED_ASC",
    ),
    "flow_runs": PrefectCloudEndpointConfig(
        name="flow_runs",
        path="/flow_runs/filter",
        filter_key="flow_runs",
        incremental_sorts={
            "start_time": "START_TIME_ASC",
            "expected_start_time": "EXPECTED_START_TIME_ASC",
        },
        incremental_fields=[
            _datetime_incremental_field("start_time"),
            _datetime_incremental_field("expected_start_time"),
        ],
        # `expected_start_time` is set on every run (including scheduled ones whose `start_time`
        # is still null), so it's the stable full-refresh paging order.
        sort="EXPECTED_START_TIME_ASC",
        partition_key="created",
        default_incremental_lookback_seconds=RUN_LOOKBACK_SECONDS,
    ),
    "task_runs": PrefectCloudEndpointConfig(
        name="task_runs",
        path="/task_runs/filter",
        filter_key="task_runs",
        # TaskRunSort has no START_TIME_ASC, so `expected_start_time` is the only cursor whose
        # server-side filter can be paired with an ascending sort.
        incremental_sorts={"expected_start_time": "EXPECTED_START_TIME_ASC"},
        incremental_fields=[_datetime_incremental_field("expected_start_time")],
        sort="EXPECTED_START_TIME_ASC",
        partition_key="created",
        default_incremental_lookback_seconds=RUN_LOOKBACK_SECONDS,
    ),
    "deployments": PrefectCloudEndpointConfig(
        name="deployments",
        path="/deployments/filter",
        # DeploymentFilter has no time-range filters, so full refresh only.
        sort="CREATED_ASC",
    ),
    "work_pools": PrefectCloudEndpointConfig(
        name="work_pools",
        path="/work_pools/filter",
        sort="NAME_ASC",
    ),
    "work_queues": PrefectCloudEndpointConfig(
        name="work_queues",
        path="/work_queues/filter",
        # The work_queues filter body accepts no `sort` at all; the table is small enough that
        # offset paging on the implicit order is acceptable for full refresh.
        sort=None,
    ),
}

ENDPOINTS = tuple(PREFECT_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PREFECT_CLOUD_ENDPOINTS.items()
}
