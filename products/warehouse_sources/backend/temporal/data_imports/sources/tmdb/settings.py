from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=False)
class TMDbEndpointConfig:
    path: str
    # Key in the JSON response holding the list of rows. "results" for the paginated list/trending
    # endpoints, "genres" for the genre lists, and None when the response body is itself a bare list
    # (the configuration languages/countries endpoints).
    data_key: Optional[str] = "results"
    # Paginated endpoints expose `page` / `total_pages` and accept a `page` query param. The reference
    # endpoints (genres, languages, countries) return everything in a single response.
    paginated: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # No TMDB v3 list endpoint exposes a server-side updated-after filter, so every endpoint is full
    # refresh only. Kept for parity with other sources and in case the changes API is wired up later.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    # Set for endpoints that run once per row of another endpoint. `parent` names that endpoint, and
    # `resolve_fields` maps each `{placeholder}` in `path` to the parent row field that fills it.
    parent: Optional[str] = None
    resolve_fields: dict[str, str] = field(default_factory=dict)


# Discover returns at most 500 pages like the curated lists. Vote count changes slowly, so this
# order keeps the same titles in the table, and in the per-title tables below, from one sync to the next.
DISCOVER_PARAMS: dict[str, Any] = {"sort_by": "vote_count.desc", "include_adult": "false"}


TMDB_ENDPOINTS: dict[str, TMDbEndpointConfig] = {
    # Movies
    "movie_popular": TMDbEndpointConfig(path="/movie/popular"),
    "movie_top_rated": TMDbEndpointConfig(path="/movie/top_rated"),
    "movie_now_playing": TMDbEndpointConfig(path="/movie/now_playing"),
    "movie_upcoming": TMDbEndpointConfig(path="/movie/upcoming"),
    # TV
    "tv_popular": TMDbEndpointConfig(path="/tv/popular"),
    "tv_top_rated": TMDbEndpointConfig(path="/tv/top_rated"),
    "tv_on_the_air": TMDbEndpointConfig(path="/tv/on_the_air"),
    "tv_airing_today": TMDbEndpointConfig(path="/tv/airing_today"),
    # People
    "person_popular": TMDbEndpointConfig(path="/person/popular"),
    # Trending (daily window)
    "trending_movies": TMDbEndpointConfig(path="/trending/movie/day"),
    "trending_tv": TMDbEndpointConfig(path="/trending/tv/day"),
    "trending_people": TMDbEndpointConfig(path="/trending/person/day"),
    # Discover
    "discover_movies": TMDbEndpointConfig(path="/discover/movie", params=DISCOVER_PARAMS),
    "discover_tv": TMDbEndpointConfig(path="/discover/tv", params=DISCOVER_PARAMS),
    # Per-title tables. Each one makes a request for every discover title, so they start disabled.
    "movie_credits": TMDbEndpointConfig(
        path="/movie/{movie_id}/credits",
        data_key=None,
        paginated=False,
        primary_keys=["movie_id", "credit_id"],
        should_sync_default=False,
        parent="discover_movies",
        resolve_fields={"movie_id": "id"},
    ),
    "tv_aggregate_credits": TMDbEndpointConfig(
        path="/tv/{series_id}/aggregate_credits",
        data_key=None,
        paginated=False,
        primary_keys=["series_id", "credit_id"],
        should_sync_default=False,
        parent="discover_tv",
        resolve_fields={"series_id": "id"},
    ),
    "tv_seasons": TMDbEndpointConfig(
        path="/tv/{series_id}",
        data_key=None,
        paginated=False,
        primary_keys=["series_id", "id"],
        should_sync_default=False,
        parent="discover_tv",
        resolve_fields={"series_id": "id"},
    ),
    "tv_episodes": TMDbEndpointConfig(
        path="/tv/{series_id}/season/{season_number}",
        data_key=None,
        paginated=False,
        primary_keys=["show_id", "id"],
        should_sync_default=False,
        parent="tv_seasons",
        resolve_fields={"series_id": "series_id", "season_number": "season_number"},
    ),
    # Reference data — single response, no pagination
    "movie_genres": TMDbEndpointConfig(path="/genre/movie/list", data_key="genres", paginated=False),
    "tv_genres": TMDbEndpointConfig(path="/genre/tv/list", data_key="genres", paginated=False),
    "languages": TMDbEndpointConfig(
        path="/configuration/languages",
        data_key=None,
        paginated=False,
        primary_keys=["iso_639_1"],
    ),
    "countries": TMDbEndpointConfig(
        path="/configuration/countries",
        data_key=None,
        paginated=False,
        primary_keys=["iso_3166_1"],
    ),
    "movie_watch_providers": TMDbEndpointConfig(
        path="/watch/providers/movie", paginated=False, primary_keys=["provider_id"]
    ),
    "tv_watch_providers": TMDbEndpointConfig(path="/watch/providers/tv", paginated=False, primary_keys=["provider_id"]),
    "watch_provider_regions": TMDbEndpointConfig(
        path="/watch/providers/regions", paginated=False, primary_keys=["iso_3166_1"]
    ),
}

ENDPOINTS = tuple(TMDB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TMDB_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in TMDB_ENDPOINTS.items()}
