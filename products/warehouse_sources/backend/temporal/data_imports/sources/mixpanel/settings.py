from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionFormat
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


@frozen
class RegionHosts:
    query_base: str  # query/app API base
    export_base: str  # raw export API base
    ingestion_base: str  # ingestion API base, which also serves lookup tables


# Mixpanel splits the heavy raw export traffic onto a separate `data*` host per
# data-residency region.
REGION_HOSTS: dict[str, RegionHosts] = {
    MixpanelRegion.US: RegionHosts(
        query_base="https://mixpanel.com",
        export_base="https://data.mixpanel.com",
        ingestion_base="https://api.mixpanel.com",
    ),
    MixpanelRegion.EU: RegionHosts(
        query_base="https://eu.mixpanel.com",
        export_base="https://data-eu.mixpanel.com",
        ingestion_base="https://api-eu.mixpanel.com",
    ),
    MixpanelRegion.IN: RegionHosts(
        query_base="https://in.mixpanel.com",
        export_base="https://data-in.mixpanel.com",
        ingestion_base="https://api-in.mixpanel.com",
    ),
}

# First sync of the raw export endpoint only pulls this far back to avoid replaying
# the entire project history in one job. Subsequent incremental syncs advance from the
# last-seen event time.
DEFAULT_EXPORT_LOOKBACK_DAYS = 365

# Funnel and retention reports are recomputed over a rolling window on every sync, because
# Mixpanel keeps revising recent buckets while conversion and return windows are still open.
REPORT_LOOKBACK_DAYS = 90
# Daily retention intervals returned per cohort, on top of Mixpanel's 0th interval.
RETENTION_INTERVAL_COUNT = 30


@dataclass(frozen=True)
class MixpanelEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable timestamp used for datetime partitioning. Must never change after a row is
    # written (event time / creation date), never `updated`/`last_seen`.
    partition_key: Optional[str] = None
    partition_format: PartitionFormat = "month"
    description: Optional[str] = None


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
        description="Only syncs the last 365 days on initial sync",
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
    # Query API: saved funnel definitions (id + name). Single request, full refresh.
    "funnels": MixpanelEndpointConfig(
        name="funnels",
        primary_keys=["funnel_id"],
    ),
    # Query API: daily step conversion for every saved funnel, one row per funnel, day and step.
    "funnel_steps": MixpanelEndpointConfig(
        name="funnel_steps",
        description="Recomputes the last 90 days on every sync",
        primary_keys=["funnel_id", "date", "step_index"],
        partition_key="date",
    ),
    # Query API: daily recurring retention across all events, one row per cohort day and interval.
    "retention": MixpanelEndpointConfig(
        name="retention",
        description="Recomputes the last 90 days on every sync",
        primary_keys=["date", "interval_index"],
        partition_key="date",
    ),
    # App API: Lexicon data dictionary, one row per event or profile schema. Full refresh.
    "lexicon_schemas": MixpanelEndpointConfig(
        name="lexicon_schemas",
        primary_keys=["entityType", "name"],
    ),
    # Ingestion API: lookup table ids and names. Mixpanel has no endpoint that reads the rows of a
    # lookup table, so only the list is synced. Full refresh.
    "lookup_tables": MixpanelEndpointConfig(
        name="lookup_tables",
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
