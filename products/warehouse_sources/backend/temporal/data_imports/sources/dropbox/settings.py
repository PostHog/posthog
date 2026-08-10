from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Synthetic primary key for team_log events: Dropbox returns no identifier on an audit
# event, so we hash the event body to get a stable, repeatable key for merges.
EVENT_ID_FIELD = "_event_id"


@dataclass(frozen=True)
class DropboxEndpointConfig:
    name: str
    path: str
    data_key: str
    primary_key: str
    # Dropbox splits paginated RPCs into a start call plus a `/continue` call that accepts only
    # the cursor. `sharing/list_shared_links` instead takes the cursor back on the same path.
    continue_path: str | None = None
    # Static request args for the start call; dynamic ones (folder path, time window) are
    # added by the transport.
    start_args: dict[str, Any] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None
    # Team endpoints act on the whole team rather than one member, so they must not carry the
    # `Dropbox-API-Select-User` header, and they need a team-scoped app to reach at all.
    is_team_endpoint: bool = False


DROPBOX_ENDPOINTS: dict[str, DropboxEndpointConfig] = {
    "files": DropboxEndpointConfig(
        name="files",
        path="/2/files/list_folder",
        continue_path="/2/files/list_folder/continue",
        data_key="entries",
        primary_key="id",
        # `include_deleted` stays off: tombstone entries carry no id, so they cannot be merged.
        start_args={
            "recursive": True,
            "include_deleted": False,
            "include_mounted_folders": True,
            "include_non_downloadable_files": True,
            "limit": 2000,
        },
    ),
    "shared_links": DropboxEndpointConfig(
        name="shared_links",
        path="/2/sharing/list_shared_links",
        data_key="links",
        primary_key="url",
    ),
    "shared_folders": DropboxEndpointConfig(
        name="shared_folders",
        path="/2/sharing/list_folders",
        continue_path="/2/sharing/list_folders/continue",
        data_key="entries",
        primary_key="shared_folder_id",
        start_args={"limit": 1000},
    ),
    "team_members": DropboxEndpointConfig(
        name="team_members",
        path="/2/team/members/list_v2",
        continue_path="/2/team/members/list_v2/continue",
        data_key="members",
        primary_key="team_member_id",
        start_args={"limit": 1000, "include_removed": False},
        is_team_endpoint=True,
    ),
    "team_events": DropboxEndpointConfig(
        name="team_events",
        path="/2/team_log/get_events",
        continue_path="/2/team_log/get_events/continue",
        data_key="events",
        primary_key=EVENT_ID_FIELD,
        start_args={"limit": 1000},
        # `time.start_time` is a real server-side filter, and an audit event's timestamp
        # never changes, so it doubles as the partition key.
        incremental_fields=[incremental_field("timestamp")],
        partition_key="timestamp",
        is_team_endpoint=True,
    ),
}

ENDPOINTS = tuple(DROPBOX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DROPBOX_ENDPOINTS.items() if config.incremental_fields
}

# Team endpoints only resolve for a team-scoped app with team scopes granted, which most
# Dropbox accounts don't have — leave them unticked so setup doesn't fail on them.
SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: not config.is_team_endpoint for name, config in DROPBOX_ENDPOINTS.items()}

DESCRIPTIONS: dict[str, str] = {
    "files": "File and folder metadata for the synced folder, listed recursively.",
    "shared_links": "Shared links created on the account's files and folders.",
    "shared_folders": "Shared folders the account is a member of.",
    "team_members": "Members of the Dropbox Business team (requires a team-scoped app).",
    "team_events": "Dropbox Business audit log events (requires a team-scoped app).",
}
