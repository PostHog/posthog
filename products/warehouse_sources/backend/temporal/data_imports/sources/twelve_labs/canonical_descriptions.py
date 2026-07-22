from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Twelve Labs v1.3 API docs (https://docs.twelvelabs.io/v1.3/api-reference).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "indexes": {
        "description": "An index groups one or more uploaded videos stored as vectors, together with the models used to process them.",
        "docs_url": "https://docs.twelvelabs.io/v1.3/api-reference/indexes",
        "columns": {
            "_id": "Unique identifier of the index, assigned by the platform.",
            "index_name": "Name of the index.",
            "created_at": "Date and time, in RFC 3339 format, the index was created.",
            "updated_at": "Date and time, in RFC 3339 format, the index was last updated.",
            "expires_at": "Date and time the index expires (null on plans without expiry).",
            "total_duration": "Total duration, in seconds, of all videos in the index.",
            "video_count": "Number of videos uploaded to the index.",
            "models": "Video understanding models enabled for the index, each with model_name and model_options.",
            "addons": "Add-ons enabled for the index.",
        },
    },
    "tasks": {
        "description": "A video indexing task tracks the upload and indexing lifecycle of a single video.",
        "docs_url": "https://docs.twelvelabs.io/v1.3/api-reference/tasks",
        "columns": {
            "_id": "Unique identifier of the video indexing task.",
            "index_id": "Identifier of the index the video is being uploaded to.",
            "video_id": "Identifier of the resulting video once indexing completes.",
            "status": "Task status: ready, uploading, validating, pending, queued, indexing, or failed.",
            "created_at": "Date and time, in RFC 3339 format, the task was created.",
            "updated_at": "Date and time, in RFC 3339 format, the task was last updated.",
            "system_metadata": "Platform-derived metadata about the video (filename, duration, width, height).",
        },
    },
    "videos": {
        "description": "A video is an indexed asset within an index, searchable and available for analysis.",
        "docs_url": "https://docs.twelvelabs.io/v1.3/api-reference/videos",
        "columns": {
            "_id": "Unique identifier of the video, assigned by the platform.",
            "index_id": "Identifier of the index the video belongs to (injected during fan-out).",
            "asset_id": "Identifier of the underlying asset associated with the video.",
            "created_at": "Date and time, in RFC 3339 format, the indexing task was created.",
            "updated_at": "Date and time, in RFC 3339 format, the video object was last updated.",
            "indexed_at": "Date and time, in RFC 3339 format, indexing completed.",
            "system_metadata": "Platform-derived metadata about the video (filename, duration, fps, width, height, size).",
        },
    },
}
