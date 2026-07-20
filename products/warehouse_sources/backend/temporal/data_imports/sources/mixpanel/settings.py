from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Mixpanel vendor API version labels. `v1` is PostHog's legacy placeholder — the source
# predates explicit versioning — and `2.0` is Mixpanel's current published API version.
MIXPANEL_API_VERSION_V1 = UNVERSIONED_API_VERSION
MIXPANEL_API_VERSION_2_0 = "2.0"

SUPPORTED_API_VERSIONS: tuple[str, ...] = (MIXPANEL_API_VERSION_V1, MIXPANEL_API_VERSION_2_0)
DEFAULT_API_VERSION = MIXPANEL_API_VERSION_2_0

# Mixpanel serves the Raw Event Export under a versioned path segment (`/api/2.0/export`).
# Both supported labels currently resolve to Mixpanel's `2.0` export path; deriving the
# segment from the pin keeps a future export-API version a one-line change here rather than
# a hunt through the request layer.
EXPORT_API_PATH_SEGMENT: dict[str, str] = {
    MIXPANEL_API_VERSION_V1: "2.0",
    MIXPANEL_API_VERSION_2_0: "2.0",
}


class MixpanelRegion(StrEnum):
    US = "us"
    EU = "eu"
    IN = "in"


# region -> (query/app API base, raw export API base). Mixpanel splits the heavy raw
# export traffic onto a separate `data*` host per data-residency region.
REGION_HOSTS: dict[str, tuple[str, str]] = {
    MixpanelRegion.US: ("https://mixpanel.com", "https://data.mixpanel.com"),
    MixpanelRegion.EU: ("https://eu.mixpanel.com", "https://data-eu.mixpanel.com"),
    MixpanelRegion.IN: ("https://in.mixpanel.com", "https://data-in.mixpanel.com"),
}

# First sync of the raw export endpoint only pulls this far back to avoid replaying
# the entire project history in one job. Subsequent incremental syncs advance from the
# last-seen event time.
DEFAULT_EXPORT_LOOKBACK_DAYS = 365


@dataclass
class MixpanelEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable timestamp used for datetime partitioning. Must never change after a row is
    # written (event time / creation date), never `updated`/`last_seen`.
    partition_key: Optional[str] = None
    partition_format: PartitionFormat = "month"


MIXPANEL_ENDPOINTS: dict[str, MixpanelEndpointConfig] = {
    # Raw Event Export API: streams every event in a date window as JSONL. The only
    # endpoint with a genuine server-side time filter (from_date/to_date), so the only
    # one that supports incremental sync.
    "export": MixpanelEndpointConfig(
        name="export",
        # Mixpanel has no single event id. `$insert_id` is the dedup key on modern events;
        # the rest of the composite distinguishes legacy events that predate `$insert_id`.
        primary_keys=["$insert_id", "event", "distinct_id", "time"],
        partition_key="time",
        partition_format="month",
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.Integer,
                "field": "time",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    # Engage API: user profiles. Session-based pagination, no reliable server-side time
    # filter -> full refresh only.
    "engage": MixpanelEndpointConfig(
        name="engage",
        primary_keys=["$distinct_id"],
    ),
    # Query API: list of cohorts. Small, single request, full refresh.
    "cohorts": MixpanelEndpointConfig(
        name="cohorts",
        primary_keys=["id"],
        partition_key="created",
    ),
    # App API: project annotations. Small, single request, full refresh.
    "annotations": MixpanelEndpointConfig(
        name="annotations",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(MIXPANEL_ENDPOINTS.keys())

# Only the raw export endpoint exposes a server-side date filter. Everything else is
# full refresh (see API verification notes in mixpanel.py).
SUPPORTS_INCREMENTAL: set[str] = {"export"}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in MIXPANEL_ENDPOINTS.items()
}
