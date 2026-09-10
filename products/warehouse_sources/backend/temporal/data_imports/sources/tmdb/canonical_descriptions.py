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
}
