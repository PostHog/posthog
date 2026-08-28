from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class AppsignalEndpointConfig:
    name: str
    # "rest" endpoints page through time windows on AppSignal's legacy JSON API;
    # "graphql" endpoints walk the incident lists with limit/offset paging.
    api: Literal["rest", "graphql"]
    # REST-only: path template under appsignal.com with an {app_id} placeholder.
    path: Optional[str] = None
    # REST-only: key the list of rows is nested under in the response body.
    data_key: Optional[str] = None
    # REST-only: extra query params sent on every request (e.g. kind=deploy).
    extra_params: dict[str, str] = field(default_factory=dict)
    # REST-only: names of the lower/upper time-bound query params for windowing.
    since_param: str = "since"
    before_param: str = "before"
    # GraphQL-only: the field on the App type holding the incident list, and the
    # selection set to request for each row.
    graphql_field: Optional[str] = None
    graphql_selection: Optional[str] = None
    primary_key: str = "id"
    # Field the time windows filter on (REST) — also the sort key within a yielded window.
    cursor_field: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Rows are immutable once written (samples). Mutable resources (deploy markers keep
    # accumulating exception counts) must merge instead of append.
    immutable_rows: bool = False


# Selection sets are built from AppSignal's published GraphQL schema reference
# (https://appsignal.com/graphql/docs). `exceptionIncidents` args (limit/offset/order) come from
# the documented ExceptionIncidentsQuery example; `performanceIncidents` mirrors the same
# resolver signature per the schema reference.
_INCIDENT_SHARED_FIELDS = """
    id
    number
    count
    state
    severity
    namespace
    description
    actionNames
    lastOccurredAt
    createdAt
    updatedAt
"""

APPSIGNAL_ENDPOINTS: dict[str, AppsignalEndpointConfig] = {
    # Exception incidents are mutable aggregates (count, state, lastOccurredAt keep changing)
    # and the GraphQL list has no server-side timestamp filter, so they sync full refresh only.
    "exception_incidents": AppsignalEndpointConfig(
        name="exception_incidents",
        api="graphql",
        graphql_field="exceptionIncidents",
        graphql_selection=_INCIDENT_SHARED_FIELDS
        + """
    exceptionName
    exceptionMessage
    firstBacktraceLine
    errorGroupingStrategy
""",
        partition_key="createdAt",
    ),
    "performance_incidents": AppsignalEndpointConfig(
        name="performance_incidents",
        api="graphql",
        graphql_field="performanceIncidents",
        graphql_selection=_INCIDENT_SHARED_FIELDS
        + """
    mean
    totalDuration
    hasNPlusOne
""",
        partition_key="createdAt",
    ),
    # Deploy markers keep mutating after creation (closed_at, exception_count, exception_rate
    # accumulate until the next deploy), so incremental syncs merge rather than append.
    "deploy_markers": AppsignalEndpointConfig(
        name="deploy_markers",
        api="rest",
        path="/api/{app_id}/markers.json",
        data_key="markers",
        extra_params={"kind": "deploy"},
        since_param="from",
        before_param="to",
        cursor_field="created_at",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Samples are immutable once recorded; `time` is a UNIX epoch integer that the API's
    # `since`/`before` params filter on server-side.
    "error_samples": AppsignalEndpointConfig(
        name="error_samples",
        api="rest",
        path="/api/{app_id}/samples/errors.json",
        data_key="log_entries",
        cursor_field="time",
        partition_key="time",
        immutable_rows=True,
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "performance_samples": AppsignalEndpointConfig(
        name="performance_samples",
        api="rest",
        path="/api/{app_id}/samples/performance.json",
        data_key="log_entries",
        cursor_field="time",
        partition_key="time",
        immutable_rows=True,
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
}

ENDPOINTS = tuple(APPSIGNAL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPSIGNAL_ENDPOINTS.items() if config.incremental_fields
}
