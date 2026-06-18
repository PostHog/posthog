# Session Recordings

## SessionRecording (`system.session_recordings`)

Metadata for session recordings captured by the PostHog SDK. The actual replay data lives in ClickHouse and object storage; this Postgres table stores recording-level metadata used for listing and filtering.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Internal UUID primary key
`session_id` | varchar(200) | NOT NULL | SDK-generated session ID (unique)
`team_id` | integer | NOT NULL | Team this recording belongs to
`distinct_id` | varchar(400) | NULL | The distinct ID of the person in this recording
`duration` | integer | NULL | Total recording duration in seconds
`active_seconds` | integer | NULL | Seconds with user activity (clicks, keystrokes, scrolling)
`inactive_seconds` | integer | NULL | Seconds without user activity
`start_time` | timestamp with tz | NULL | When the recording started
`end_time` | timestamp with tz | NULL | When the recording ended
`click_count` | integer | NULL | Number of click events
`keypress_count` | integer | NULL | Number of keypress events
`mouse_activity_count` | integer | NULL | Number of mouse activity events
`console_log_count` | integer | NULL | Number of console.log entries
`console_warn_count` | integer | NULL | Number of console.warn entries
`console_error_count` | integer | NULL | Number of console.error entries
`start_url` | varchar(512) | NULL | URL when the recording started
`deleted` | boolean | NULL | Whether the recording has been deleted
`created_at` | timestamp with tz | NULL | When this metadata record was created
`retention_period_days` | integer | NULL | How long the recording is retained
`storage_version` | varchar(20) | NULL | Storage format version

### Key Relationships

- Each recording belongs to a **Team** (`team_id`)
- Recordings are linked to persons via `distinct_id`
- Recordings can be added to **Session Recording Playlists** via `SessionRecordingPlaylistItem`

### Important Notes

- Recordings are created by the SDK, not via the API
- The `session_id` field is the user-facing ID (used in URLs and API calls), not the internal `id`
- Activity data (click_count, duration, etc.) is populated from ClickHouse and may be NULL for older recordings
- Use `deleted IS NOT TRUE` to filter out soft-deleted recordings
