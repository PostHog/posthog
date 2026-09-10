from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField

# GIPHY's content endpoints return current snapshots and expose no server-side
# created_at/updated_at filter, so every endpoint is full-refresh only. The GIF
# object carries `import_datetime`, but there's no `import_datetime_gte`-style
# query param to filter on, so we can't do incremental sync.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}


@dataclass
class GiphyEndpointConfig:
    name: str
    # Path under the API base (https://api.giphy.com/v1).
    path: str
    # Column(s) that uniquely identify a row across the whole table.
    primary_keys: list[str]
    # Key in the response body the rows live under.
    data_key: str = "data"
    # Largest offset GIPHY will serve for this endpoint. Trending caps at 499 and
    # search at 4999; requesting a larger offset 400s, so pagination stops here.
    max_offset: int | None = None
    # Search endpoints (`/search`) require a `q` query term supplied by the user.
    requires_query: bool = False
    # `/trending/searches` returns a flat list of strings rather than objects and
    # has no pagination, so it's normalized and fetched as a single page.
    is_term_list: bool = False
    # Whether the table is selected for sync by default in the wizard.
    should_sync_default: bool = True


# GIPHY's public REST API is a content-discovery API, not per-account business
# data, so streams are built around trending content, user-supplied search
# queries, and the category taxonomy.
GIPHY_ENDPOINTS: dict[str, GiphyEndpointConfig] = {
    "gifs_trending": GiphyEndpointConfig(
        name="gifs_trending",
        path="/gifs/trending",
        primary_keys=["id"],
        max_offset=499,
    ),
    "stickers_trending": GiphyEndpointConfig(
        name="stickers_trending",
        path="/stickers/trending",
        primary_keys=["id"],
        max_offset=499,
    ),
    "gifs_search": GiphyEndpointConfig(
        name="gifs_search",
        path="/gifs/search",
        primary_keys=["id"],
        max_offset=4999,
        requires_query=True,
    ),
    "stickers_search": GiphyEndpointConfig(
        name="stickers_search",
        path="/stickers/search",
        primary_keys=["id"],
        max_offset=4999,
        requires_query=True,
    ),
    "categories": GiphyEndpointConfig(
        name="categories",
        path="/gifs/categories",
        primary_keys=["name_encoded"],
    ),
    "trending_search_terms": GiphyEndpointConfig(
        name="trending_search_terms",
        path="/trending/searches",
        primary_keys=["search_term"],
        is_term_list=True,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(GIPHY_ENDPOINTS.keys())
