from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class AppsignalEndpointConfig:
    name: str
    # "rest" endpoints page through time windows on AppSignal's legacy JSON API;
    # "graphql" endpoints walk the incident lists with limit/offset paging;
    # "custom" endpoints name a walker in `appsignal.py` (see `walker`).
    api: Literal["rest", "graphql", "custom"]
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
    # Name of the walker that builds the rows for a "custom" endpoint. The Public API V2
    # surface and the app list each need their own request and fan-out shape, so they cannot
    # share the declarative "rest" and "graphql" paths.
    walker: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
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
    # Every table below is keyed by an app ID, so the app list is the lookup that resolves
    # those IDs to a name, environment and organization. `viewer` is used rather than
    # `organization(slug:)` because the source form asks for an app ID, never an org slug.
    "apps": AppsignalEndpointConfig(
        name="apps",
        api="custom",
        walker="apps",
        partition_key="createdAt",
    ),
    # Log lines live only on the Public API V2: the GraphQL API exposes no log line field.
    "log_lines": AppsignalEndpointConfig(
        name="log_lines",
        api="custom",
        walker="log_lines",
        # A log line ID is unique within its source, not across the sources of an app.
        primary_keys=["source_id", "id"],
        cursor_field="timestamp",
        partition_key="timestamp",
        immutable_rows=True,
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # The metric catalog: one row per metric name, with its type and the tag keys it carries.
    # This is what makes `metric_timeseries` readable, and it is the only way to discover
    # which custom metrics an app reports.
    "metric_names": AppsignalEndpointConfig(
        name="metric_names",
        api="custom",
        walker="metric_names",
        primary_keys=["name"],
    ),
    # All custom and platform metric data. The GraphQL metrics API is deprecated, so V2 is
    # the only supported source for it.
    "metric_timeseries": AppsignalEndpointConfig(
        name="metric_timeseries",
        api="custom",
        walker="metric_timeseries",
        # A series ID is composed of the metric name, its sorted tags and the field, so it is
        # unique table-wide and a bucket is identified by the series plus its timestamp.
        primary_keys=["series_id", "timestamp"],
        cursor_field="timestamp",
        partition_key="timestamp",
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "performance_traces": AppsignalEndpointConfig(
        name="performance_traces",
        api="custom",
        walker="performance_traces",
        primary_keys=["site_id", "trace_id"],
        cursor_field="time",
        partition_key="time",
        immutable_rows=True,
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Spans are fanned out per trace, so each row carries the parent trace's `time`. The
    # sweep is driven by that field, and a span's own `start_time` can precede it.
    "trace_spans": AppsignalEndpointConfig(
        name="trace_spans",
        api="custom",
        walker="trace_spans",
        primary_keys=["trace_id", "span_id"],
        cursor_field="trace_time",
        partition_key="trace_time",
        immutable_rows=True,
        incremental_fields=[
            {
                "label": "trace_time",
                "type": IncrementalFieldType.DateTime,
                "field": "trace_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(APPSIGNAL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPSIGNAL_ENDPOINTS.items() if config.incremental_fields
}
