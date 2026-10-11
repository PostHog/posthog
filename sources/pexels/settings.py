from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class PexelsEndpointConfig:
    name: str
    path: str  # relative to PEXELS_BASE_URL
    # Key in the JSON response that holds the list of rows ("photos", "videos" or "collections").
    data_key: str
    # Search endpoints reject a request without a `query`; they're only offered when the user
    # configures a search query on the source.
    requires_query: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    description: str | None = None


PEXELS_ENDPOINTS: dict[str, PexelsEndpointConfig] = {
    "curated_photos": PexelsEndpointConfig(
        name="curated_photos",
        path="/v1/curated",
        data_key="photos",
        description="A real-time selection of photos curated by the Pexels team.",
    ),
    "popular_videos": PexelsEndpointConfig(
        name="popular_videos",
        path="/videos/popular",
        data_key="videos",
        description="The current most popular Pexels videos.",
    ),
    "featured_collections": PexelsEndpointConfig(
        name="featured_collections",
        path="/v1/collections/featured",
        data_key="collections",
        description="Collections featured by the Pexels team.",
    ),
    "my_collections": PexelsEndpointConfig(
        name="my_collections",
        path="/v1/collections",
        data_key="collections",
        description="Collections owned by the authenticated Pexels account.",
    ),
    "search_photos": PexelsEndpointConfig(
        name="search_photos",
        path="/v1/search",
        data_key="photos",
        requires_query=True,
        description="Photos matching the configured search query. Full refresh only.",
    ),
    "search_videos": PexelsEndpointConfig(
        name="search_videos",
        path="/videos/search",
        data_key="videos",
        requires_query=True,
        description="Videos matching the configured search query. Full refresh only.",
    ),
}

ENDPOINTS = tuple(PEXELS_ENDPOINTS.keys())

# Pexels exposes no server-side timestamp/cursor filter on any endpoint, and its resource objects
# (photos, videos, collections) carry no created/updated timestamp. Every table is therefore full
# refresh only: no incremental fields and no datetime partition key.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in PEXELS_ENDPOINTS}
