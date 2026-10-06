from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "recently_played": {
        "description": (
            "One row for each track a connected Spotify account played. Podcast episodes are not included."
        ),
        "docs_url": "https://developer.spotify.com/documentation/web-api/reference/get-recently-played",
        "columns": {
            "account_id": "Spotify account ID of the connected account that played the track.",
            "played_at": "Date and time the track was played.",
            "track_id": "Spotify ID of the track. Null for a local file.",
            "track_name": "Name of the track.",
            "primary_artist_id": "Spotify ID of the first artist credited on the track.",
            "primary_artist_name": "Name of the first artist credited on the track.",
            "album_id": "Spotify ID of the album the track appears on.",
            "album_name": "Name of the album the track appears on.",
            "duration_ms": "Length of the track in milliseconds.",
            "explicit": "Whether the track has explicit lyrics.",
            "context_type": "Type of object the track was played from: artist, playlist, album or show.",
            "context_uri": "Spotify URI of the object the track was played from.",
            "track": "Full track object as Spotify returned it, including every credited artist.",
        },
    },
    "accounts": {
        "description": "One row for each Spotify account connected to this project.",
        "columns": {
            "account_id": "Spotify account ID of the connected account. It never changes.",
            "display_name": "Name shown on the Spotify profile, or the Spotify user ID when the profile has no name.",
            "connected_by_email": "Email of the PostHog user who connected the account.",
            "connected_by_name": "Name of the PostHog user who connected the account.",
            "connected_at": "Date and time the account was first connected.",
        },
    },
}
