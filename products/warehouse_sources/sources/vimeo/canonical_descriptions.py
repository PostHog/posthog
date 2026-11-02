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
    "folder_videos": {
        "description": "Videos in each folder of the authenticated user. A video appears once for each folder that holds it.",
        "docs_url": "https://developer.vimeo.com/api/reference/folders",
        "columns": {
            "folder_uri": "URI of the folder that holds the video.",
            "uri": "Relative URI that identifies the video.",
            "name": "Video title.",
            "created_time": "Time when the video was created, in ISO 8601 format.",
        },
    },
    "showcase_videos": {
        "description": "Videos in each showcase of the authenticated user. A video appears once for each showcase that holds it.",
        "docs_url": "https://developer.vimeo.com/api/reference/showcases",
        "columns": {
            "showcase_uri": "URI of the showcase that holds the video.",
            "uri": "Relative URI that identifies the video.",
            "name": "Video title.",
            "created_time": "Time when the video was created, in ISO 8601 format.",
        },
    },
    "video_comments": {
        "description": "Top-level comments on the videos of the authenticated user.",
        "docs_url": "https://developer.vimeo.com/api/reference/videos",
        "columns": {
            "video_uri": "URI of the video that the comment is about.",
            "uri": "Unique identifier of the comment.",
            "text": "Content of the comment.",
            "created_on": "Time when the comment was posted, in ISO 8601 format.",
            "user": "User who posted the comment.",
        },
    },
    "video_comment_replies": {
        "description": "Replies to the comments on the videos of the authenticated user.",
        "docs_url": "https://developer.vimeo.com/api/reference/videos",
        "columns": {
            "comment_uri": "URI of the comment that the reply answers.",
            "uri": "Unique identifier of the reply.",
            "text": "Content of the reply.",
            "created_on": "Time when the reply was posted, in ISO 8601 format.",
            "user": "User who posted the reply.",
        },
    },
    "video_likes": {
        "description": "Users who liked each video of the authenticated user. A user appears once for each video that they liked.",
        "docs_url": "https://developer.vimeo.com/api/reference/videos",
        "columns": {
            "video_uri": "URI of the video that the user liked.",
            "uri": "URI that identifies the user.",
            "name": "Display name of the user.",
        },
    },
}
