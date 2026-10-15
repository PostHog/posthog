from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "videos": {
        "description": "Generated and translated videos, including their status and output artifacts.",
        "docs_url": "https://developers.heygen.com/reference/list-videos",
        "columns": {
            "id": "Unique video identifier.",
            "created_at": "Video creation time in Unix seconds.",
            "completed_at": "Video completion time in Unix seconds.",
            "duration": "Video duration in seconds.",
            "video_url": "Temporary download URL for the rendered video.",
            "folder_id": "Identifier of the folder containing the video.",
        },
    },
    "video_translations": {
        "description": "Video translation jobs with languages, processing status, and output artifacts.",
        "docs_url": "https://developers.heygen.com/reference/list-video-translations",
        "columns": {
            "id": "Unique translation job identifier.",
            "created_at": "Translation job creation time in Unix seconds.",
            "input_language": "Detected or requested source language.",
            "output_language": "Target language code.",
            "duration": "Video duration in seconds.",
        },
    },
    "video_agent_sessions": {
        "description": "Video composition sessions for the authenticated user.",
        "docs_url": "https://developers.heygen.com/reference/list-video-agent-sessions",
        "columns": {
            "session_id": "Unique video composition session identifier.",
            "created_at": "Session creation time in Unix seconds.",
            "title": "Generated session title.",
        },
    },
    "avatar_groups": {
        "description": "Private avatar identities containing one or more looks.",
        "docs_url": "https://developers.heygen.com/reference/list-avatar-groups",
        "columns": {
            "id": "Unique avatar group identifier.",
            "created_at": "Avatar creation time in Unix seconds.",
            "looks_count": "Number of looks belonging to this avatar.",
            "default_voice_id": "Identifier of the avatar's default voice.",
        },
    },
    "avatar_looks": {
        "description": "Private avatar looks representing outfits, poses, and styles available for video creation.",
        "docs_url": "https://developers.heygen.com/reference/list-avatar-looks",
        "columns": {
            "id": "Unique look identifier used as avatar_id in video requests.",
            "group_id": "Identifier of the avatar group containing the look.",
            "supported_api_engines": "Rendering engines compatible with this look.",
        },
    },
    "voices": {
        "description": "Private voices available to the authenticated account.",
        "docs_url": "https://developers.heygen.com/reference/list-voices",
        "columns": {
            "voice_id": "Unique voice identifier.",
            "language": "Primary language of the voice.",
            "preview_audio_url": "URL for an audio sample of the voice.",
        },
    },
    "templates": {
        "description": "Workspace video templates available through the API.",
        "docs_url": "https://developers.heygen.com/reference/list-templates",
        "columns": {
            "id": "Unique template identifier.",
            "created_at": "Template creation time in Unix seconds.",
            "updated_at": "Time of the last template update in Unix seconds.",
            "aspect_ratio": "Aspect ratio of the template output.",
        },
    },
    "account": {
        "description": "Current account profile and billing balance, including wallet or subscription credits.",
        "docs_url": "https://developers.heygen.com/reference/get-current-user",
        "columns": {
            "username": "Account username.",
            "billing_type": "Billing model used by the account.",
            "wallet": "Current wallet balance and automatic reload settings.",
            "subscription": "Subscription plan and credit balance.",
            "usage_based": "Usage billing details.",
        },
    },
}
