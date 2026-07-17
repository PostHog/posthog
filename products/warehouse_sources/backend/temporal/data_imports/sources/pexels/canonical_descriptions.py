"""Canonical, documentation-sourced descriptions for Pexels endpoints and columns.

Sourced from the official Pexels API reference (https://www.pexels.com/api/documentation/).
Keyed by the endpoint names in `settings.py` `PEXELS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Pexels table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_PHOTO_COLUMNS = {
    "id": "Unique identifier for the photo.",
    "width": "Real width of the photo in pixels.",
    "height": "Real height of the photo in pixels.",
    "url": "Pexels URL where the photo is located.",
    "photographer": "Name of the photographer who took the photo.",
    "photographer_url": "Pexels profile URL of the photographer.",
    "photographer_id": "Unique identifier of the photographer.",
    "avg_color": "Average color of the photo, useful as a placeholder while the image loads.",
    "src": "Object of URLs pointing to different sizes/crops of the photo.",
    "liked": "Whether the authenticated user has liked the photo.",
    "alt": "Text description of the photo for use in an alt attribute.",
}

_VIDEO_COLUMNS = {
    "id": "Unique identifier for the video.",
    "width": "Real width of the video in pixels.",
    "height": "Real height of the video in pixels.",
    "duration": "Duration of the video in seconds.",
    "url": "Pexels URL where the video is located.",
    "image": "URL of a screenshot preview image for the video.",
    "avg_color": "Average color of the video, when available.",
    "full_res": "URL of the full-resolution video, when available.",
    "tags": "List of tags associated with the video.",
    "user": "Object describing the videographer (id, name, profile url).",
    "video_files": "List of downloadable/streamable video file variants (quality, file type, dimensions, link).",
    "video_pictures": "List of preview picture frames extracted from the video.",
}

_COLLECTION_COLUMNS = {
    "id": "Unique identifier for the collection.",
    "title": "Title of the collection.",
    "description": "Description of the collection.",
    "private": "Whether the collection is private.",
    "media_count": "Total number of media items (photos and videos) in the collection.",
    "photos_count": "Number of photos in the collection.",
    "videos_count": "Number of videos in the collection.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "curated_photos": {
        "description": "A real-time selection of photos curated by the Pexels team.",
        "docs_url": "https://www.pexels.com/api/documentation/#photos-curated",
        "columns": _PHOTO_COLUMNS,
    },
    "search_photos": {
        "description": "Photos returned by the Pexels photo search for the configured query.",
        "docs_url": "https://www.pexels.com/api/documentation/#photos-search",
        "columns": _PHOTO_COLUMNS,
    },
    "popular_videos": {
        "description": "The current most popular Pexels videos.",
        "docs_url": "https://www.pexels.com/api/documentation/#videos-popular",
        "columns": _VIDEO_COLUMNS,
    },
    "search_videos": {
        "description": "Videos returned by the Pexels video search for the configured query.",
        "docs_url": "https://www.pexels.com/api/documentation/#videos-search",
        "columns": _VIDEO_COLUMNS,
    },
    "featured_collections": {
        "description": "Collections featured by the Pexels team.",
        "docs_url": "https://www.pexels.com/api/documentation/#collections-featured",
        "columns": _COLLECTION_COLUMNS,
    },
    "my_collections": {
        "description": "Collections owned by the authenticated Pexels account.",
        "docs_url": "https://www.pexels.com/api/documentation/#collections-all",
        "columns": _COLLECTION_COLUMNS,
    },
}
