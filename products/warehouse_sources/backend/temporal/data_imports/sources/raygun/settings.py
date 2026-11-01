from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Raygun's data API is a single global host (no regional variants) exposing v3 REST/JSON.
RAYGUN_BASE_URL = "https://api.raygun.com/v3"

# Page size for offset/count pagination. The API caps `count` at 500; 100 keeps individual
# responses small while limiting the number of round trips.
PAGE_SIZE = 100

# The metrics endpoints return at most 4,320 points per request. Hourly buckets over 30-day windows
# stay well under that, and requests start on an hour boundary so bucket times are stable across syncs.
METRICS_GRANULARITY = "1h"
METRICS_WINDOW = timedelta(days=30)
METRICS_INITIAL_LOOKBACK = timedelta(days=30)
# Re-read the last few hourly buckets on each incremental sync, because late-arriving data restates them.
METRICS_INCREMENTAL_LOOKBACK_SECONDS = 3 * 60 * 60


@dataclass(frozen=True)
class RaygunNestedParent:
    # Per-application listing whose rows each own a child listing (two-level fan-out).
    path: str
    orderby: str
    # Column each child row gets with the parent's identifier, since child rows don't carry it.
    identifier_column: str
    # Parent field compared against the incremental watermark: a parent older than the watermark
    # has no new child rows, so its child listing is not requested.
    skip_below_watermark_field: Optional[str] = None


@dataclass(frozen=True)
class RaygunMetricsRequest:
    aggregation: str
    metrics: tuple[str, ...]


@dataclass
class RaygunEndpointConfig:
    name: str
    # Path relative to RAYGUN_BASE_URL. Fan-out children carry a `{application_identifier}`
    # placeholder resolved once per application.
    path: str
    primary_keys: list[str]
    # `orderby` value passed on every request. Offset pagination over data that is being
    # inserted concurrently can skip or duplicate rows, so we always sort by a stable
    # (immutable or create-time) field to keep page boundaries deterministic. Unset for the
    # metrics endpoints, which aren't paginated.
    orderby: Optional[str] = None
    # Stable create-time field used for datetime partitioning. Only set when the field is
    # guaranteed present on every row (in the API's `required` set) — never `lastSeenAt`/
    # `updatedAt`, which move over time and would rewrite partitions each sync.
    partition_key: Optional[str] = None
    # When True, iterate every application and call `path` per application. When False the
    # endpoint is a single top-level list.
    fan_out_over_applications: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Set for child endpoints under a per-application parent listing; the child `path` then also
    # carries a `{parent_identifier}` placeholder.
    nested_parent: Optional[RaygunNestedParent] = None
    # Values for the child listing's `state eq <value>` filter. Each value is requested separately
    # and written to `state_column`, because the API returns the state only through the filter.
    state_filters: tuple[str, ...] = ()
    state_column: Optional[str] = None
    # Set for the POST time-series metrics endpoints: one request per entry per time window.
    metrics_requests: tuple[RaygunMetricsRequest, ...] = ()


# Raygun list endpoints have no server-side "updated since" filter (only offset/count pagination
# plus an `orderby`), so they sync as a full refresh. The exceptions: the metrics endpoints take a
# time range, and error instances sort newest first under error groups that report when they last
# occurred, so an incremental sync stops at the watermark instead of reading all history.
RAYGUN_ENDPOINTS: dict[str, RaygunEndpointConfig] = {
    "applications": RaygunEndpointConfig(
        name="applications",
        path="/applications",
        primary_keys=["identifier"],
        orderby="name",
    ),
    "error_groups": RaygunEndpointConfig(
        name="error_groups",
        path="/applications/{application_identifier}/error-groups",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="createdAt",
        partition_key="createdAt",
        fan_out_over_applications=True,
    ),
    "deployments": RaygunEndpointConfig(
        name="deployments",
        path="/applications/{application_identifier}/deployments",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="deployedAt",
        fan_out_over_applications=True,
    ),
    "customers": RaygunEndpointConfig(
        name="customers",
        path="/applications/{application_identifier}/customers",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="firstSeenAt",
        fan_out_over_applications=True,
    ),
    "sessions": RaygunEndpointConfig(
        name="sessions",
        path="/applications/{application_identifier}/sessions",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="startedAt",
        partition_key="startedAt",
        fan_out_over_applications=True,
    ),
    "pages": RaygunEndpointConfig(
        name="pages",
        path="/applications/{application_identifier}/pages",
        primary_keys=["applicationIdentifier", "identifier"],
        orderby="uri",
        fan_out_over_applications=True,
    ),
    "error_instances": RaygunEndpointConfig(
        name="error_instances",
        path="/applications/{application_identifier}/error-groups/{parent_identifier}/instances",
        primary_keys=["applicationIdentifier", "errorGroupIdentifier", "identifier"],
        orderby="occurredOn desc",
        partition_key="occurredOn",
        nested_parent=RaygunNestedParent(
            path="/applications/{application_identifier}/error-groups",
            orderby="createdAt",
            identifier_column="errorGroupIdentifier",
            skip_below_watermark_field="lastOccurredAt",
        ),
        incremental_fields=[
            {
                "label": "occurredOn",
                "type": IncrementalFieldType.DateTime,
                "field": "occurredOn",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "deployment_error_groups": RaygunEndpointConfig(
        name="deployment_error_groups",
        path="/applications/{application_identifier}/deployments/{parent_identifier}/error-groups",
        primary_keys=["applicationIdentifier", "deploymentIdentifier", "identifier"],
        orderby="createdAt",
        partition_key="createdAt",
        nested_parent=RaygunNestedParent(
            path="/applications/{application_identifier}/deployments",
            orderby="deployedAt",
            identifier_column="deploymentIdentifier",
        ),
        # `stillOccurring` is left out: it repeats every active error group for every deployment,
        # which costs the most requests and says nothing about what the deployment changed.
        state_filters=("new", "regressed"),
        state_column="deploymentState",
    ),
    "error_metrics": RaygunEndpointConfig(
        name="error_metrics",
        path="/metrics/{application_identifier}/errors/time-series",
        primary_keys=["applicationIdentifier", "metric", "aggregation", "time"],
        partition_key="time",
        metrics_requests=(RaygunMetricsRequest(aggregation="count", metrics=("errorInstances",)),),
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
    "page_metrics": RaygunEndpointConfig(
        name="page_metrics",
        path="/metrics/{application_identifier}/pages/time-series",
        primary_keys=["applicationIdentifier", "metric", "aggregation", "time"],
        partition_key="time",
        metrics_requests=(
            RaygunMetricsRequest(aggregation="count", metrics=("pageViews",)),
            *(
                RaygunMetricsRequest(
                    aggregation=aggregation,
                    metrics=(
                        "loadTime",
                        "firstPaint",
                        "firstContentfulPaint",
                        "largestContentfulPaint",
                        "firstInputDelay",
                        "cumulativeLayoutShift",
                        "interactionToNextPaint",
                    ),
                )
                for aggregation in ("average", "median", "p95", "p99")
            ),
        ),
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
}

METRICS_ENDPOINTS = tuple(name for name, config in RAYGUN_ENDPOINTS.items() if config.metrics_requests)

ENDPOINTS = tuple(RAYGUN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RAYGUN_ENDPOINTS.items()
}
