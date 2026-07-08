from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Mux API reference (https://www.mux.com/docs/api-reference).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "assets": {
        "description": "A Mux Video Asset: an encoded piece of video or audio ready for streaming.",
        "docs_url": "https://www.mux.com/docs/api-reference/video/assets/list-assets",
        "columns": {
            "id": "Unique identifier for the Asset.",
            "created_at": "Time the Asset was created, as a Unix timestamp (seconds since epoch).",
            "status": "Status of the Asset: preparing, ready, or errored.",
            "duration": "Duration of the Asset in seconds (max duration for a single Asset is 12 hours).",
            "max_stored_resolution": "Maximum resolution that has been stored for the Asset.",
            "max_stored_frame_rate": "Maximum frame rate (in frames per second) that has been stored for the Asset.",
            "aspect_ratio": "Aspect ratio of the Asset, as a string like '16:9'.",
            "playback_ids": "Array of Playback ID objects used to create playback URLs for the Asset.",
            "tracks": "The individual media tracks (video, audio, text) that make up the Asset.",
            "mp4_support": "Level of support for MP4 playback of the Asset.",
            "master_access": "Level of access to the master (highest-quality) version of the Asset.",
            "passthrough": "Arbitrary user-supplied metadata set when creating the Asset.",
            "live_stream_id": "Unique identifier of the live stream that created this Asset, if any.",
            "test": "True if this is a test Asset (created with a free Mux account).",
        },
    },
    "live_streams": {
        "description": "A Mux Video Live Stream: a configured RTMP/SRT ingest endpoint that produces Assets.",
        "docs_url": "https://www.mux.com/docs/api-reference/video/live-streams/list-live-streams",
        "columns": {
            "id": "Unique identifier for the Live Stream.",
            "created_at": "Time the Live Stream was created, as a Unix timestamp (seconds since epoch).",
            "status": "Status of the Live Stream: idle, active, or disabled.",
            "playback_ids": "Array of Playback ID objects used to create playback URLs for the Live Stream.",
            "new_asset_settings": "Settings applied to Assets created from this Live Stream.",
            "passthrough": "Arbitrary user-supplied metadata set when creating the Live Stream.",
            "reconnect_window": "Seconds Mux waits for a disconnected stream to reconnect before finishing.",
            "max_continuous_duration": "Maximum duration in seconds a single broadcast can run.",
            "latency_mode": "Latency mode of the Live Stream: low, reduced, or standard.",
            "active_asset_id": "Unique identifier of the Asset currently being recorded, if active.",
            "recent_asset_ids": "Asset IDs created from recent broadcasts of this Live Stream.",
            "test": "True if this is a test Live Stream.",
        },
    },
    "uploads": {
        "description": "A Mux Video Direct Upload: an authenticated URL for pushing source media directly to Mux.",
        "docs_url": "https://www.mux.com/docs/api-reference/video/direct-uploads/list-direct-uploads",
        "columns": {
            "id": "Unique identifier for the Direct Upload.",
            "status": "Status of the upload: waiting, asset_created, errored, cancelled, or timed_out.",
            "asset_id": "Unique identifier of the Asset created from this upload, once available.",
            "new_asset_settings": "Settings applied to the Asset created from this upload.",
            "cors_origin": "Origin allowed to use the upload URL from a browser.",
            "timeout": "Seconds the upload URL is valid for before it times out.",
            "error": "Object describing the error, if the upload failed.",
            "test": "True if this is a test Direct Upload.",
        },
    },
    "playback_restrictions": {
        "description": "A Mux Video Playback Restriction: rules controlling where and how videos can be played.",
        "docs_url": "https://www.mux.com/docs/api-reference/video/playback-restrictions/list-playback-restrictions",
        "columns": {
            "id": "Unique identifier for the Playback Restriction.",
            "created_at": "Time the Playback Restriction was created, as a Unix timestamp (seconds since epoch).",
            "updated_at": "Time the Playback Restriction was last updated, as a Unix timestamp (seconds since epoch).",
            "referrer": "Rules for which HTTP referrer domains are allowed to play videos.",
            "user_agent": "Rules for which user agents are allowed to play videos.",
        },
    },
    "transcription_vocabularies": {
        "description": "A Mux Video Transcription Vocabulary: a collection of phrases that improve transcription accuracy.",
        "docs_url": "https://www.mux.com/docs/api-reference/video/transcription-vocabularies/list-transcription-vocabularies",
        "columns": {
            "id": "Unique identifier for the Transcription Vocabulary.",
            "name": "Human-readable name for the Transcription Vocabulary.",
            "phrases": "Phrases, names, and other words to boost when transcribing audio.",
            "created_at": "Time the Transcription Vocabulary was created, as a Unix timestamp (seconds since epoch).",
            "updated_at": "Time the Transcription Vocabulary was last updated, as a Unix timestamp (seconds since epoch).",
        },
    },
    "signing_keys": {
        "description": "A Mux signing key: an RSA key pair used to sign JWTs for secured playback URLs.",
        "docs_url": "https://www.mux.com/docs/api-reference/system/signing-keys/list-signing-keys",
        "columns": {
            "id": "Unique identifier for the Signing Key (used as the JWT key ID).",
            "created_at": "Time the Signing Key was created, as a Unix timestamp (seconds since epoch).",
        },
    },
}
