from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Instana's paginated application-monitoring catalogs accept a `pageSize` param; their analyze
# endpoints cap page sizes at 200, so stay at that known-safe value here too.
PAGE_SIZE = 200

# A self-hosted server the user controls can return a full page on every request while never
# signalling the end of pagination, keeping the catalog walk (and its ingestion) running for the
# whole activity. Two independent bounds stop the walk and fail non-retryably:
#
#  - A cumulative wall-clock budget is the effective bound. A page count alone doesn't cap worker
#    time — each page may stream for MAX_DOWNLOAD_SECONDS, so a slow host could stay under a page
#    cap yet hold the worker for days. 30 minutes is far longer than any real catalog walk (which
#    is minutes) but far below the import activity timeout, so a slow-drip host is evicted quickly.
#  - A page ceiling is a secondary record/memory bound (10k pages x 200 = 2M records), far above
#    any real catalog, so a legitimate inventory is never truncated.
MAX_CATALOG_WALK_SECONDS = 30 * 60
MAX_CATALOG_PAGES = 10_000

# `/api/events` has no pagination — the window itself bounds the response — so wide ranges must be
# chunked. One-day chunks keep responses small while the first sync stays at ~30 requests.
EVENTS_WINDOW_CHUNK_MS = 24 * 60 * 60 * 1000

# First sync / full refresh reaches back this far. Instana retains events for a limited window
# (typically ~31 days), so asking for more returns nothing extra.
EVENTS_DEFAULT_LOOKBACK_DAYS = 30

# `/api/infrastructure-monitoring/snapshots` has a `size` cap instead of pagination. The window
# only needs to cover entities currently reporting, so keep it short.
SNAPSHOTS_WINDOW_MS = 60 * 60 * 1000
SNAPSHOTS_MAX_SIZE = 1000

PaginationStyle = Literal["page", "none"]


@dataclass
class InstanaEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records. ``None`` means the body itself is the list.
    data_path: Optional[str] = None
    primary_key: str = "id"
    pagination: PaginationStyle = "none"
    # Only `events` filters server-side (from/to epoch-ms window on the event `start`); everything
    # else is a config/topology catalog with no updated-since cursor, so it ships full refresh.
    is_events: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Extra query params sent on every request.
    extra_params: dict[str, str] = field(default_factory=dict)

    @property
    def supports_incremental(self) -> bool:
        return self.is_events


def _start_incremental_fields() -> list[IncrementalField]:
    # Instana timestamps are epoch milliseconds (int64), not ISO datetimes.
    return [
        {
            "label": "start",
            "type": IncrementalFieldType.Integer,
            "field": "start",
            "field_type": IncrementalFieldType.Integer,
        }
    ]


# Endpoint catalog, verified against the official OpenAPI spec
# (https://instana.github.io/openapi/openapi.yaml). Instana has no Airbyte/Fivetran connector to
# mirror, so coverage follows what the UI surfaces: events, the application-monitoring catalogs
# (applications/services/endpoints), website + synthetic monitoring configs, alerting settings,
# and the infrastructure snapshot inventory. Metric time-series and trace analytics endpoints are
# POST-with-body cursor APIs and are intentionally out of scope for the first release.
INSTANA_ENDPOINTS: dict[str, InstanaEndpointConfig] = {
    "events": InstanaEndpointConfig(
        name="events",
        path="/api/events",
        primary_key="eventId",
        is_events=True,
        incremental_fields=_start_incremental_fields(),
    ),
    "applications": InstanaEndpointConfig(
        name="applications",
        path="/api/application-monitoring/applications",
        data_path="items",
        pagination="page",
    ),
    "services": InstanaEndpointConfig(
        name="services",
        path="/api/application-monitoring/services",
        data_path="items",
        pagination="page",
    ),
    "endpoints": InstanaEndpointConfig(
        name="endpoints",
        path="/api/application-monitoring/applications/services/endpoints",
        data_path="items",
        pagination="page",
    ),
    "websites": InstanaEndpointConfig(
        name="websites",
        path="/api/website-monitoring/config",
    ),
    "synthetic_tests": InstanaEndpointConfig(
        name="synthetic_tests",
        path="/api/synthetics/settings/tests",
    ),
    "alerting_channels": InstanaEndpointConfig(
        name="alerting_channels",
        path="/api/events/settings/alertingChannels",
    ),
    "alert_configs": InstanaEndpointConfig(
        name="alert_configs",
        path="/api/events/settings/alerts",
    ),
    "infrastructure_snapshots": InstanaEndpointConfig(
        name="infrastructure_snapshots",
        path="/api/infrastructure-monitoring/snapshots",
        data_path="items",
        primary_key="snapshotId",
        extra_params={"windowSize": str(SNAPSHOTS_WINDOW_MS), "size": str(SNAPSHOTS_MAX_SIZE)},
    ),
}

ENDPOINTS = tuple(INSTANA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INSTANA_ENDPOINTS.items()
}
