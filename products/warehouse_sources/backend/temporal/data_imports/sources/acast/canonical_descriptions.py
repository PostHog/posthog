from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "shows": {
        "description": "Podcast shows assigned to the user who owns the Acast API key.",
        "docs_url": "https://developers.acast.com/",
        "columns": {
            "_id": "The unique identifier for the show.",
            "title": "The title of the show.",
            "summary": "The description of the show, including HTML formatting.",
            "creationDate": "The date and time when the show was created.",
            "publishDate": "The publication date and time of the show.",
            "episodesCount": "The number of episodes in the show.",
            "isPrivate": "Whether the show is private.",
            "Lang": "The language of the show.",
            "Status": "The publication status of the show.",
        },
    },
    "episodes": {
        "description": "Podcast episodes for each show assigned to the user who owns the Acast API key.",
        "docs_url": "https://developers.acast.com/",
        "columns": {
            "_id": "The identifier for the episode.",
            "show_id": "The identifier of the parent show, added during import.",
            "Show": "The identifier of the show that contains the episode.",
            "title": "The title of the episode.",
            "summary": "The description of the episode, including HTML formatting.",
            "creationDate": "The date and time when the episode was created.",
            "lastEditedDate": "The date and time when the episode was last edited.",
            "publishDate": "The publication date and time of the episode.",
            "Status": "The publication status of the episode.",
            "Duration": "The duration of the episode in seconds.",
            "episodeNumber": "The episode number within the show.",
            "Season": "The season number of the episode.",
            "Markers": "Advertisement markers with their identifiers, placements, and start times.",
        },
    },
}
