from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "channels": {
        "description": "Public metadata, statistics, branding, and related playlists for the selected YouTube channel.",
        "docs_url": "https://developers.google.com/youtube/v3/docs/channels",
        "columns": {
            "id": "The unique YouTube channel ID.",
            "snippet": "The channel title, description, thumbnails, and publication time.",
            "statistics": "The channel view, subscriber, and video counts.",
            "contentDetails": "Related playlists, including the channel uploads playlist.",
            "brandingSettings": "The channel branding settings.",
        },
    },
    "videos": {
        "description": "Public video details and current statistics for videos in the channel uploads playlist.",
        "docs_url": "https://developers.google.com/youtube/v3/docs/videos",
        "columns": {
            "id": "The unique YouTube video ID.",
            "snippet": "The video title, description, channel ID, thumbnails, and publication time.",
            "contentDetails": "The video duration, definition, captions, and region restrictions.",
            "statistics": "The video view, like, and comment counts.",
            "status": "The video upload status, privacy status, and license.",
        },
    },
    "playlists": {
        "description": "Public playlists owned by the selected channel. This list excludes the system uploads playlist.",
        "docs_url": "https://developers.google.com/youtube/v3/docs/playlists",
        "columns": {
            "id": "The YouTube playlist ID.",
            "snippet": "The playlist title, description, channel ID, thumbnails, and creation time.",
            "contentDetails": "The number of items in the playlist.",
            "status": "The playlist privacy status.",
        },
    },
    "playlist_items": {
        "description": "Items in the channel public playlists, including video references and positions.",
        "docs_url": "https://developers.google.com/youtube/v3/docs/playlistItems",
        "columns": {
            "id": "The playlist item ID.",
            "playlist_id": "The parent playlist ID.",
            "snippet": "The item title, playlist position, channel ID, and video reference.",
            "contentDetails": "The video ID and video publication time.",
            "status": "The playlist item privacy status.",
        },
    },
    "comment_threads": {
        "description": "Public comment threads for the channel and its videos. Reply bodies are not included.",
        "docs_url": "https://developers.google.com/youtube/v3/docs/commentThreads",
        "columns": {
            "id": "The comment thread ID.",
            "snippet": "The top-level comment, channel ID, video ID, and total reply count.",
        },
    },
}
