from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

# Curated set of Git/DORA metrics pulled from the Measurements V2 endpoint. Names are taken from the
# public metric glossary; each entry pairs a metric with the aggregation LinearB documents for it
# (duration/size metrics take a percentile, counts take no agg). The response keys each value as
# "<name>:<agg>" (or just "<name>" for counts), which the transport flattens into columns.
MEASUREMENT_METRICS: tuple[tuple[str, Optional[str]], ...] = (
    ("branch.computed.cycle_time", "p75"),
    ("branch.time_to_pr", "p75"),
    ("branch.time_to_review", "p75"),
    ("branch.review_time", "p75"),
    ("branch.time_to_prod", "p75"),
    ("pr.merged.size", "avg"),
    ("pr.merged", None),
    ("pr.new", None),
    ("pr.reviews", None),
    ("pr.merged.without.review.count", None),
    ("releases.count", None),
    ("commit.total.count", None),
    ("commit.total_changes", None),
    ("commit.activity.new_work.count", None),
    ("commit.activity.refactor.count", None),
    ("commit.activity.rework.count", None),
)

# Default window (in days) pulled on every measurements sync. Measurements are a computed time series;
# a full refresh re-pulls the window each run and merge dedupes on [after, organization_id].
MEASUREMENTS_DEFAULT_WINDOW_DAYS = 90


@dataclass
class LinearbEndpointConfig:
    name: str
    path: str
    method: Literal["GET", "POST"] = "GET"
    # Key inside the wrapped `{total, items}` response holding the row array. `None` for the
    # measurements endpoint, which returns a bare array of time-window objects.
    data_selector: Optional[str] = "items"
    # Name of the page-size query param this endpoint accepts (`page_size` vs `limit`), and its cap.
    # `None` when the endpoint documents no pagination params (a single response holds every row).
    page_size_param: Optional[str] = None
    page_size: Optional[int] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style field,
    # which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    partition_format: Literal["month", "week", "day"] = "month"
    should_sync_default: bool = True
    # Server-side timestamp filter params are documented for deployments (after/before) but left
    # unverified against a live account, so every endpoint currently ships full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


LINEARB_ENDPOINTS: dict[str, LinearbEndpointConfig] = {
    "teams": LinearbEndpointConfig(
        name="teams",
        path="/api/v2/teams",
        page_size_param="page_size",
        page_size=50,
        partition_key="created_at",
    ),
    "users": LinearbEndpointConfig(
        name="users",
        path="/api/v1/users",
        page_size_param="page_size",
        page_size=50,
        partition_key="created_at",
    ),
    "services": LinearbEndpointConfig(
        name="services",
        path="/api/v1/services",
    ),
    "deployments": LinearbEndpointConfig(
        name="deployments",
        path="/api/v1/deployments",
        page_size_param="limit",
        page_size=100,
    ),
    # Measurements is a POST metric query rather than a list endpoint. It is plan-gated (LinearB
    # Business/Enterprise only), so it is off by default; users on an eligible plan opt in.
    "measurements": LinearbEndpointConfig(
        name="measurements",
        path="/api/v2/measurements",
        method="POST",
        data_selector=None,
        primary_keys=["after", "organization_id"],
        partition_key="after",
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(LINEARB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LINEARB_ENDPOINTS.items()
}
