from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

APPSTACK_API_BASE_URL = "https://api.appstack.tech/api/v1"

# Documented default and maximum page size for GET /export (`limit` is 1-10000).
PAGE_SIZE = 10000

# Attribution events can surface in the export after their event_time (late postbacks, delayed
# matching), so each incremental run re-reads a trailing window; merge dedupes on event_id. The
# publication delay is undocumented, so a full day is a conservative default.
DEFAULT_INCREMENTAL_LOOKBACK_SECONDS = 24 * 60 * 60


@dataclass
class AppstackEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field to partition by — an event's time never changes after export.
    partition_key: Optional[str] = None


# Appstack's whole public data surface is one endpoint: GET /export returns the app's attributed
# events (installs and in-app events matched to the ad campaigns that drove them), ordered by
# event_time ascending, paged with limit/offset within a window starting at the required
# `timestamp` param (Unix seconds). API keys are scoped to a single app, so one source connection
# covers one app.
APPSTACK_ENDPOINTS: dict[str, AppstackEndpointConfig] = {
    "events": AppstackEndpointConfig(
        name="events",
        path="/export",
        primary_keys=["event_id"],
        partition_key="event_time",
        incremental_fields=[incremental_field("event_time")],
    ),
}

ENDPOINTS = tuple(APPSTACK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPSTACK_ENDPOINTS.items() if config.incremental_fields
}
