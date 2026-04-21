# Session Recording Playlists

## SessionRecordingPlaylist (`system.session_recording_playlists`)

Saved views for organizing session recordings. There are two types: collections (manually curated lists) and filters (saved filter criteria that dynamically match recordings).

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key
`short_id` | varchar(12) | NOT NULL | Human-friendly short identifier (used in URLs and API lookups)
`name` | varchar(400) | NULL | Human-readable playlist name
`derived_name` | varchar(400) | NULL | Auto-generated name based on filter criteria
`description` | text | NOT NULL | Playlist description (can be blank)
`team_id` | integer | NOT NULL | Team this playlist belongs to
`pinned` | boolean | NOT NULL | Whether the playlist is pinned to the top
`deleted` | boolean | NOT NULL | Whether the playlist is soft-deleted
`filters` | jsonb | NOT NULL | JSON filter criteria for dynamic matching (only used when type is 'filters')
`type` | varchar(50) | NULL | Playlist type: 'collection' or 'filters'
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`created_by_id` | integer | NULL | FK to the user who created this playlist
`last_modified_at` | timestamp with tz | NOT NULL | When the playlist was last updated
`last_modified_by_id` | integer | NULL | FK to the user who last modified this playlist

### Key Relationships

- Each playlist belongs to a **Team** (`team_id`)
- Playlists are created by a **User** (`created_by_id`)
- Collection playlists contain recordings via `SessionRecordingPlaylistItem` (not exposed as a system table)

### Important Notes

- The `type` field determines behavior:
  - `collection` — manually curated list of recordings
  - `filters` — saved filter criteria that dynamically match recordings
- Use `short_id` for lookups (this is the API lookup field)
- Use `deleted = false` to filter out soft-deleted playlists
- The `filters` field is only meaningful when `type = 'filters'`
