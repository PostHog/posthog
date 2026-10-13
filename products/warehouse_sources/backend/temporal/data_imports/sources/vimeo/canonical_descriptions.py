from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "videos": {
        "description": "Videos uploaded by the authenticated user.",
        "docs_url": "https://developer.vimeo.com/api/reference/videos",
        "columns": {
            "uri": "Relative URI that identifies the video.",
            "name": "Video title.",
            "description": "Description of the video content.",
            "created_time": "Time when the video was created, in ISO 8601 format.",
            "modified_time": "Time when the video metadata last changed, in ISO 8601 format.",
            "duration": "Video length in seconds. Zero means Vimeo has not calculated the length.",
        },
    },
    "folders": {
        "description": "Folders that belong to the authenticated user.",
        "docs_url": "https://developer.vimeo.com/api/reference/folders",
        "columns": {
            "uri": "URI that identifies the folder.",
            "name": "Folder name.",
            "created_time": "Time when the folder was created, in ISO 8601 format.",
            "modified_time": "Time when the folder last changed, in ISO 8601 format.",
        },
    },
    "showcases": {
        "description": "Showcases that belong to the authenticated user.",
        "docs_url": "https://developer.vimeo.com/api/reference/showcases",
        "columns": {
            "uri": "URI that identifies the showcase.",
            "name": "Showcase display name.",
            "description": "Description of the showcase content.",
            "created_time": "Time when the showcase was created, in ISO 8601 format.",
            "modified_time": "Time when the showcase last changed, in ISO 8601 format.",
            "duration": "Combined length of the showcase videos, in seconds.",
        },
    },
}
