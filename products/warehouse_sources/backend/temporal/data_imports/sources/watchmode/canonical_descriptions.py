from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "titles": {
        "description": "Every movie and TV title in Watchmode's catalog, with external IDs for cross-referencing IMDb and TMDB.",
        "docs_url": "https://api.watchmode.com/docs/",
        "columns": {
            "id": "Watchmode's unique ID for the title.",
            "title": "Name of the title.",
            "year": "Year the title was released.",
            "imdb_id": "IMDb ID for the title.",
            "tmdb_id": "TMDB ID for the title.",
            "tmdb_type": "Whether the TMDB ID refers to a movie or a TV entry.",
            "type": "Type of the title: movie, tv_series, tv_movie, tv_special, tv_miniseries or short_film.",
        },
    },
    "releases": {
        "description": "Titles recently released or coming soon to major streaming services, one row per title per service.",
        "docs_url": "https://api.watchmode.com/docs/",
        "columns": {
            "id": "Watchmode's unique ID for the title.",
            "title": "Name of the title.",
            "type": "Type of the title: movie, tv_series, tv_movie, tv_special, tv_miniseries or short_film.",
            "imdb_id": "IMDb ID for the title.",
            "tmdb_id": "TMDB ID for the title.",
            "tmdb_type": "Whether the TMDB ID refers to a movie or a TV entry.",
            "season_number": "Season number arriving on the service, for TV series releases.",
            "poster_url": "URL of the title's poster image.",
            "source_release_date": "Date the title becomes available on the service.",
            "source_id": "Watchmode ID of the streaming service the title is released on.",
            "source_name": "Name of the streaming service the title is released on.",
            "is_original": "Whether the title is an original production of the streaming service.",
        },
    },
    "sources": {
        "description": "All streaming services Watchmode tracks availability for, with app deep-link schemes and supported regions.",
        "docs_url": "https://api.watchmode.com/docs/",
        "columns": {
            "id": "Watchmode's unique ID for the streaming source.",
            "name": "Name of the streaming source.",
            "type": "How the service offers titles: sub (subscription), free, purchase or tve (TV everywhere).",
            "logo_100px": "URL of the source's logo image.",
            "regions": "Country codes the source is available in.",
        },
    },
    "regions": {
        "description": "Countries Watchmode provides streaming availability data for.",
        "docs_url": "https://api.watchmode.com/docs/",
        "columns": {
            "country": "2-letter country code for the region.",
            "name": "Name of the country.",
        },
    },
    "networks": {
        "description": "TV networks known to Watchmode, usable as filters on the titles endpoint.",
        "docs_url": "https://api.watchmode.com/docs/",
        "columns": {
            "id": "Watchmode's unique ID for the network.",
            "name": "Name of the TV network.",
            "origin_country": "Country the network originates from.",
            "tmdb_id": "TMDB ID for the network.",
        },
    },
    "genres": {
        "description": "Genre names and IDs, usable as filters on the titles endpoint.",
        "docs_url": "https://api.watchmode.com/docs/",
        "columns": {
            "id": "Watchmode's unique ID for the genre.",
            "name": "Name of the genre.",
        },
    },
}
