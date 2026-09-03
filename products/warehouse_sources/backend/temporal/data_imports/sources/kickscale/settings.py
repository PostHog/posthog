from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# The OpenAPI document declares no `servers` entry, so the base URL is hardcoded.
KICKSCALE_BASE_URL = "https://api.kickscale.com"

# Kickscale documents a 20-row default page size with a maximum recommended 100. Responses are a
# bare JSON array with no total-count field, so pagination stops once a page returns fewer than
# this many rows.
DEFAULT_PAGE_SIZE = 100

# Comments, ratings, CRM links and re-analysis can land on a meeting/call after its `date`, and
# the API has no updated-since filter — re-scan a trailing window on every incremental sync so
# those late edits aren't missed (the merge dedupes on `id`).
INCREMENTAL_LOOKBACK_SECONDS = 14 * 24 * 60 * 60


@frozen
class KickscaleEndpointConfig:
    name: str
    path: str
    primary_key: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None


KICKSCALE_ENDPOINTS: dict[str, KickscaleEndpointConfig] = {
    "meetings": KickscaleEndpointConfig(
        name="meetings",
        path="/meetings",
        primary_key=["id"],
        # `date` is the only field the API accepts a server-side filter on (`startDate` /
        # `endDate`); it's the meeting's start time and doesn't move once the meeting happened.
        incremental_fields=[incremental_field("date")],
        partition_key="date",
    ),
    "calls": KickscaleEndpointConfig(
        name="calls",
        path="/calls",
        primary_key=["id"],
        incremental_fields=[incremental_field("date")],
        partition_key="date",
    ),
}

ENDPOINTS = tuple(KICKSCALE_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KICKSCALE_ENDPOINTS.items()
}
