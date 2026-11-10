import dataclasses
from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import UNVERSIONED_API_VERSION, DependentEndpointConfig, IncrementalField

# Simplecast's live REST API is labeled "2.0" (same https://api.simplecast.com host and Bearer
# auth the client already uses). UNVERSIONED_API_VERSION ("v1") is the framework placeholder that
# pre-versioning source rows carry; both labels resolve to the one available API, so no request
# branches on the version yet. Simplecast has announced but not shipped header-based version
# selection, so wiring the version onto requests is deferred until that contract is known.
SIMPLECAST_API_VERSION_2_0 = "2.0"
SUPPORTED_VERSIONS = (UNVERSIONED_API_VERSION, SIMPLECAST_API_VERSION_2_0)
DEFAULT_VERSION = SIMPLECAST_API_VERSION_2_0


# The list endpoints accept a `limit` of up to 100; the largest page minimises round trips.
PAGE_SIZE = 100

# Every fan-out child stamps the parent podcast's `id` onto its rows as `podcast_id`.
_PODCAST_FANOUT = DependentEndpointConfig(
    parent_name="podcasts",
    resolve_param="podcast_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "podcast_id"},
)


@dataclass(frozen=True)
class SimpleCastEndpointConfig:
    name: str
    path: str
    # Simplecast resource IDs are globally unique UUIDs, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    data_selector: str = "collection"
    # False for analytics reports that return the whole series in one response with no `pages`.
    paginated: bool = True
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# All endpoints are full refresh only: Simplecast exposes no server-side updated-since filter on
# its lists, and the analytics reports return running totals that change on every sync.
SIMPLECAST_ENDPOINTS: dict[str, SimpleCastEndpointConfig] = {
    "podcasts": SimpleCastEndpointConfig(name="podcasts", path="/podcasts"),
    "episodes": SimpleCastEndpointConfig(
        name="episodes",
        path="/podcasts/{podcast_id}/episodes",
        fanout=dataclasses.replace(_PODCAST_FANOUT, child_params={"sort": "created_at_asc"}),
    ),
    "downloads": SimpleCastEndpointConfig(
        name="downloads",
        path="/analytics/downloads?podcast={podcast_id}",
        primary_keys=["podcast_id", "interval"],
        data_selector="by_interval",
        paginated=False,
        fanout=dataclasses.replace(_PODCAST_FANOUT, child_params={"interval": "day"}),
    ),
    "listeners": SimpleCastEndpointConfig(
        name="listeners",
        path="/analytics/listeners?podcast={podcast_id}",
        primary_keys=["podcast_id", "interval"],
        data_selector="by_interval",
        paginated=False,
        fanout=dataclasses.replace(_PODCAST_FANOUT, child_params={"interval": "day"}),
    ),
    "episode_downloads": SimpleCastEndpointConfig(
        name="episode_downloads",
        path="/analytics/episodes?podcast={podcast_id}",
        fanout=_PODCAST_FANOUT,
    ),
    "episode_listeners": SimpleCastEndpointConfig(
        name="episode_listeners",
        path="/analytics/episodes/listeners?podcast={podcast_id}",
        fanout=_PODCAST_FANOUT,
    ),
}

ENDPOINTS = tuple(SIMPLECAST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
