from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField


@frozen
class YoutubeDataEndpoint:
    name: str
    path: str
    part: str
    params: dict[str, str | int] = field(default_factory=dict)
    primary_keys: tuple[str, ...] = ("id",)
    partition_keys: tuple[str, ...] = ("id",)
    partition_mode: Literal["md5"] = "md5"
    partition_count: int = 16
    page_size: int = 50
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


# These list methods have no timestamp filter. Their metadata and statistics can change between syncs.
# Request shapes follow the Google discovery spec; they need verification with a live account.
ENDPOINTS: dict[str, YoutubeDataEndpoint] = {
    "channels": YoutubeDataEndpoint(
        name="channels",
        path="channels",
        part="snippet,contentDetails,statistics,brandingSettings",
    ),
    "videos": YoutubeDataEndpoint(
        name="videos",
        path="videos?id={video_id}",
        part="snippet,contentDetails,statistics,status",
        fanout=DependentEndpointConfig(
            parent_name="uploads",
            resolve_param="video_id",
            resolve_field="contentDetails.videoId",
            include_from_parent=[],
        ),
    ),
    "playlists": YoutubeDataEndpoint(
        name="playlists",
        path="playlists",
        part="snippet,contentDetails,status",
        params={"maxResults": 50},
    ),
    "playlist_items": YoutubeDataEndpoint(
        name="playlist_items",
        # Checkpoints use the resolved path, so the query must identify each parent.
        path="playlistItems?playlistId={playlist_id}",
        part="snippet,contentDetails,status",
        params={"maxResults": 50},
        primary_keys=("playlist_id", "id"),
        partition_keys=("playlist_id", "id"),
        fanout=DependentEndpointConfig(
            parent_name="playlists",
            resolve_param="playlist_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "playlist_id"},
        ),
    ),
    "comment_threads": YoutubeDataEndpoint(
        name="comment_threads",
        path="commentThreads",
        part="snippet",
        params={"maxResults": 100, "order": "time", "textFormat": "plainText"},
    ),
}

FANOUT_PARENTS = {
    "playlists": ENDPOINTS["playlists"],
    "uploads": YoutubeDataEndpoint(
        name="uploads", path="playlistItems", part="contentDetails", params={"maxResults": 50}
    ),
}

INCREMENTAL_FIELDS = {name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()}
