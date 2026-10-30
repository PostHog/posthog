from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_MOVIE_COLUMNS = {
    "id": "TMDB's unique identifier for the movie.",
    "title": "Localized display title of the movie.",
    "original_title": "Title in the movie's original language.",
    "original_language": "ISO 639-1 code of the movie's original language.",
    "overview": "Plot summary / synopsis.",
    "release_date": "Theatrical release date (YYYY-MM-DD); may be empty for unreleased titles.",
    "popularity": "TMDB popularity score, recomputed daily.",
    "vote_average": "Mean user rating on a 0–10 scale.",
    "vote_count": "Number of user votes contributing to vote_average.",
    "genre_ids": "List of TMDB genre IDs (join against movie_genres).",
    "poster_path": "Relative path to the poster image, appended to the TMDB image base URL.",
    "backdrop_path": "Relative path to the backdrop image, appended to the TMDB image base URL.",
    "adult": "Whether the title is flagged as adult content.",
    "video": "Whether the entry represents a video (e.g. a direct-to-video release).",
}

_TV_COLUMNS = {
    "id": "TMDB's unique identifier for the TV show.",
    "name": "Localized display name of the show.",
    "original_name": "Name in the show's original language.",
    "original_language": "ISO 639-1 code of the show's original language.",
    "overview": "Plot summary / synopsis.",
    "first_air_date": "Date the show first aired (YYYY-MM-DD); may be empty for unreleased shows.",
    "origin_country": "List of ISO 3166-1 country codes where the show originated.",
    "popularity": "TMDB popularity score, recomputed daily.",
    "vote_average": "Mean user rating on a 0–10 scale.",
    "vote_count": "Number of user votes contributing to vote_average.",
    "genre_ids": "List of TMDB genre IDs (join against tv_genres).",
    "poster_path": "Relative path to the poster image, appended to the TMDB image base URL.",
    "backdrop_path": "Relative path to the backdrop image, appended to the TMDB image base URL.",
}

_PERSON_COLUMNS = {
    "id": "TMDB's unique identifier for the person.",
    "name": "Person's name.",
    "known_for_department": "Department the person is best known for (e.g. Acting, Directing).",
    "popularity": "TMDB popularity score, recomputed daily.",
    "gender": "Gender code (0 unknown, 1 female, 2 male, 3 non-binary).",
    "profile_path": "Relative path to the profile image, appended to the TMDB image base URL.",
    "adult": "Whether the person is flagged as adult-content related.",
    "known_for": "List of the movies/TV shows the person is best known for.",
}

_GENRE_COLUMNS = {
    "id": "TMDB genre identifier, referenced by genre_ids on movies/TV shows.",
    "name": "Human-readable genre name.",
}

_WATCH_PROVIDER_COLUMNS = {
    "provider_id": "TMDB's unique identifier for the watch provider (primary key).",
    "provider_name": "Display name of the provider.",
    "logo_path": "Relative path to the provider logo image.",
    "display_priority": "Default sort position of the provider.",
    "display_priorities": "Sort position of the provider per country, keyed by ISO 3166-1 code.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "movie_popular": {
        "description": "Movies ordered by TMDB popularity.",
        "docs_url": "https://developer.themoviedb.org/reference/movie-popular-list",
        "columns": _MOVIE_COLUMNS,
    },
    "movie_top_rated": {
        "description": "Top rated movies on TMDB.",
        "docs_url": "https://developer.themoviedb.org/reference/movie-top-rated-list",
        "columns": _MOVIE_COLUMNS,
    },
    "movie_now_playing": {
        "description": "Movies currently playing in theaters.",
        "docs_url": "https://developer.themoviedb.org/reference/movie-now-playing-list",
        "columns": _MOVIE_COLUMNS,
    },
    "movie_upcoming": {
        "description": "Movies releasing in theaters soon.",
        "docs_url": "https://developer.themoviedb.org/reference/movie-upcoming-list",
        "columns": _MOVIE_COLUMNS,
    },
    "tv_popular": {
        "description": "TV shows ordered by TMDB popularity.",
        "docs_url": "https://developer.themoviedb.org/reference/tv-series-popular-list",
        "columns": _TV_COLUMNS,
    },
    "tv_top_rated": {
        "description": "Top rated TV shows on TMDB.",
        "docs_url": "https://developer.themoviedb.org/reference/tv-series-top-rated-list",
        "columns": _TV_COLUMNS,
    },
    "tv_on_the_air": {
        "description": "TV shows airing in the next 7 days.",
        "docs_url": "https://developer.themoviedb.org/reference/tv-series-on-the-air-list",
        "columns": _TV_COLUMNS,
    },
    "tv_airing_today": {
        "description": "TV shows airing today.",
        "docs_url": "https://developer.themoviedb.org/reference/tv-series-airing-today-list",
        "columns": _TV_COLUMNS,
    },
    "person_popular": {
        "description": "People ordered by TMDB popularity.",
        "docs_url": "https://developer.themoviedb.org/reference/person-popular-list",
        "columns": _PERSON_COLUMNS,
    },
    "trending_movies": {
        "description": "Movies trending on TMDB over the last day.",
        "docs_url": "https://developer.themoviedb.org/reference/trending-movies",
        "columns": _MOVIE_COLUMNS,
    },
    "trending_tv": {
        "description": "TV shows trending on TMDB over the last day.",
        "docs_url": "https://developer.themoviedb.org/reference/trending-tv",
        "columns": _TV_COLUMNS,
    },
    "trending_people": {
        "description": "People trending on TMDB over the last day.",
        "docs_url": "https://developer.themoviedb.org/reference/trending-people",
        "columns": _PERSON_COLUMNS,
    },
    "movie_genres": {
        "description": "Official list of movie genres and their IDs.",
        "docs_url": "https://developer.themoviedb.org/reference/genre-movie-list",
        "columns": _GENRE_COLUMNS,
    },
    "tv_genres": {
        "description": "Official list of TV genres and their IDs.",
        "docs_url": "https://developer.themoviedb.org/reference/genre-tv-list",
        "columns": _GENRE_COLUMNS,
    },
    "languages": {
        "description": "Languages TMDB supports, keyed by ISO 639-1 code.",
        "docs_url": "https://developer.themoviedb.org/reference/configuration-languages",
        "columns": {
            "iso_639_1": "ISO 639-1 two-letter language code (primary key).",
            "english_name": "Language name in English.",
            "name": "Language name in its own language.",
        },
    },
    "countries": {
        "description": "Countries TMDB supports, keyed by ISO 3166-1 code.",
        "docs_url": "https://developer.themoviedb.org/reference/configuration-countries",
        "columns": {
            "iso_3166_1": "ISO 3166-1 two-letter country code (primary key).",
            "english_name": "Country name in English.",
            "native_name": "Country name in its native language.",
        },
    },
    "discover_movies": {
        "description": "Up to 10,000 movies from TMDB's discover endpoint, ordered by vote count (most-voted first).",
        "docs_url": "https://developer.themoviedb.org/reference/discover-movie",
        "columns": _MOVIE_COLUMNS,
    },
    "discover_tv": {
        "description": "Up to 10,000 TV shows from TMDB's discover endpoint, ordered by vote count (most-voted first).",
        "docs_url": "https://developer.themoviedb.org/reference/discover-tv",
        "columns": _TV_COLUMNS,
    },
    "movie_credits": {
        "description": "Cast and crew credits for each movie in discover_movies, one row per credit.",
        "docs_url": "https://developer.themoviedb.org/reference/movie-credits",
        "columns": {
            "movie_id": "TMDB ID of the movie the credit belongs to (join against the movie tables).",
            "credit_id": "TMDB's unique identifier for the credit.",
            "credit_type": "Either 'cast' or 'crew'.",
            "id": "TMDB ID of the person credited (join against the people tables).",
            "name": "Person's name.",
            "original_name": "Person's name in its original script.",
            "known_for_department": "Department the person is best known for.",
            "character": "Character played. Cast credits only.",
            "cast_id": "Position identifier of the cast entry. Cast credits only.",
            "order": "Billing order of the cast member, starting at 0. Cast credits only.",
            "department": "Department of the crew job, e.g. Directing. Crew credits only.",
            "job": "Crew job title, e.g. Director. Crew credits only.",
        },
    },
    "tv_aggregate_credits": {
        "description": "Cast and crew credits across all seasons of each TV show in discover_tv, one row per role or job.",
        "docs_url": "https://developer.themoviedb.org/reference/tv-series-aggregate-credits",
        "columns": {
            "series_id": "TMDB ID of the TV show the credit belongs to (join against the TV tables).",
            "credit_id": "TMDB's unique identifier for the role or job.",
            "credit_type": "Either 'cast' or 'crew'.",
            "id": "TMDB ID of the person credited (join against the people tables).",
            "name": "Person's name.",
            "character": "Character played in this role. Cast credits only.",
            "job": "Crew job title. Crew credits only.",
            "department": "Department of the crew job. Crew credits only.",
            "episode_count": "Number of episodes the person has in this role or job.",
            "total_episode_count": "Number of episodes the person has across all roles or jobs.",
            "order": "Billing order of the cast member. Cast credits only.",
        },
    },
    "tv_seasons": {
        "description": "Seasons of each TV show in discover_tv, from the show's details.",
        "docs_url": "https://developer.themoviedb.org/reference/tv-series-details",
        "columns": {
            "series_id": "TMDB ID of the TV show the season belongs to.",
            "id": "TMDB's unique identifier for the season.",
            "season_number": "Season number. Season 0 holds specials.",
            "name": "Season name.",
            "overview": "Season summary.",
            "air_date": "Date the season first aired (YYYY-MM-DD).",
            "episode_count": "Number of episodes in the season.",
            "vote_average": "Mean user rating on a 0–10 scale.",
            "poster_path": "Relative path to the season poster image.",
        },
    },
    "tv_episodes": {
        "description": "Episodes of every season of each TV show in discover_tv.",
        "docs_url": "https://developer.themoviedb.org/reference/tv-season-details",
        "columns": {
            "id": "TMDB's unique identifier for the episode.",
            "show_id": "TMDB ID of the TV show the episode belongs to.",
            "season_number": "Season number of the episode.",
            "episode_number": "Episode number within the season.",
            "episode_type": "Episode type, e.g. standard or finale.",
            "name": "Episode title.",
            "overview": "Episode summary.",
            "air_date": "Date the episode aired (YYYY-MM-DD).",
            "runtime": "Runtime in minutes.",
            "production_code": "Production code of the episode.",
            "vote_average": "Mean user rating on a 0–10 scale.",
            "vote_count": "Number of user votes contributing to vote_average.",
            "still_path": "Relative path to the episode still image.",
            "crew": "List of crew members credited on the episode.",
            "guest_stars": "List of guest stars credited on the episode.",
        },
    },
    "movie_watch_providers": {
        "description": "Streaming, rental and purchase providers TMDB lists for movies.",
        "docs_url": "https://developer.themoviedb.org/reference/watch-providers-movie-list",
        "columns": _WATCH_PROVIDER_COLUMNS,
    },
    "tv_watch_providers": {
        "description": "Streaming, rental and purchase providers TMDB lists for TV shows.",
        "docs_url": "https://developer.themoviedb.org/reference/watch-provider-tv-list",
        "columns": _WATCH_PROVIDER_COLUMNS,
    },
    "watch_provider_regions": {
        "description": "Countries that TMDB has watch provider data for.",
        "docs_url": "https://developer.themoviedb.org/reference/watch-providers-available-regions",
        "columns": {
            "iso_3166_1": "ISO 3166-1 two-letter country code (primary key).",
            "english_name": "Country name in English.",
            "native_name": "Country name in its native language.",
        },
    },
}
