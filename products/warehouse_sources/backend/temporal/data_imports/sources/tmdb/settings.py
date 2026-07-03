from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
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
}

ENDPOINTS = tuple(TMDB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TMDB_ENDPOINTS.items()
}
