from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "shows": {
        "description": "Every TV show in the TVmaze database, from the paginated show index.",
        "docs_url": "https://www.tvmaze.com/api#show-index",
        "columns": {
            "id": "Unique TVmaze identifier for the show.",
            "url": "URL of the show's page on tvmaze.com.",
            "name": "Name of the show.",
            "type": "Show type, e.g. Scripted, Reality, Animation, Documentary.",
            "language": "Primary language the show is produced in.",
            "genres": "List of genres the show belongs to.",
            "status": "Airing status, e.g. Running, Ended, To Be Determined, In Development.",
            "runtime": "Scheduled runtime of an episode in minutes.",
            "averageRuntime": "Average runtime across the show's episodes in minutes.",
            "premiered": "Date the show first premiered.",
            "ended": "Date the show ended, if it has.",
            "officialSite": "URL of the show's official website.",
            "schedule": "When the show airs: time of day and days of the week.",
            "rating": "Weighted average of user ratings on TVmaze.",
            "weight": "Popularity weight (0-100) used by TVmaze to rank search results.",
            "network": "Broadcast network the show airs on, including its country.",
            "webChannel": "Streaming/web channel the show airs on, if not a broadcast network.",
            "dvdCountry": "Country of the DVD release ordering, when episodes follow DVD order.",
            "externals": "Identifiers for the show in external databases (IMDb, TheTVDB, TVRage).",
            "image": "URLs of the show's poster image in medium and original sizes.",
            "summary": "Synopsis of the show as HTML.",
            "updated": "UNIX timestamp of when the show was last modified on TVmaze.",
            "_links": "HAL links to related API resources such as the previous and next episode.",
        },
    },
    "people": {
        "description": "Every person (cast and crew) in the TVmaze database, from the paginated person index.",
        "docs_url": "https://www.tvmaze.com/api#people-index",
        "columns": {
            "id": "Unique TVmaze identifier for the person.",
            "url": "URL of the person's page on tvmaze.com.",
            "name": "Name of the person.",
            "country": "Country the person was born in.",
            "birthday": "Date of birth.",
            "deathday": "Date of death, if applicable.",
            "gender": "Gender of the person.",
            "image": "URLs of the person's headshot in medium and original sizes.",
            "updated": "UNIX timestamp of when the person was last modified on TVmaze.",
            "_links": "HAL links to related API resources.",
        },
    },
    "show_updates": {
        "description": "Last-modified timestamp for every show, useful to detect which shows changed between syncs.",
        "docs_url": "https://www.tvmaze.com/api#show-updates",
        "columns": {
            "id": "Unique TVmaze identifier for the show.",
            "updated": "UNIX timestamp of when the show was last modified on TVmaze.",
        },
    },
    "person_updates": {
        "description": "Last-modified timestamp for every person, useful to detect which people changed between syncs.",
        "docs_url": "https://www.tvmaze.com/api#person-updates",
        "columns": {
            "id": "Unique TVmaze identifier for the person.",
            "updated": "UNIX timestamp of when the person was last modified on TVmaze.",
        },
    },
}
