/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Student: 'student',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * * `collection` - Collection
 * * `filters` - Filters
 */
export type SessionRecordingPlaylistPlaylistTypeEnumApi =
    (typeof SessionRecordingPlaylistPlaylistTypeEnumApi)[keyof typeof SessionRecordingPlaylistPlaylistTypeEnumApi]

export const SessionRecordingPlaylistPlaylistTypeEnumApi = {
    Collection: 'collection',
    Filters: 'filters',
} as const

/**
 * * `new` - new
 * * `pin` - pin
 * * `duplicate` - duplicate
 */
export type SessionRecordingPlaylistCreationMethodEnumApi =
    (typeof SessionRecordingPlaylistCreationMethodEnumApi)[keyof typeof SessionRecordingPlaylistCreationMethodEnumApi]

export const SessionRecordingPlaylistCreationMethodEnumApi = {
    New: 'new',
    Pin: 'pin',
    Duplicate: 'duplicate',
} as const

export type SessionRecordingPlaylistApiRecordingsCounts = { [key: string]: { [key: string]: number | boolean | null } }

export interface SessionRecordingPlaylistApi {
    readonly id: number
    readonly short_id: string
    /**
     * Human-readable name for the playlist.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    derived_name?: string | null
    /** Optional description of the playlist's purpose or contents. */
    description?: string
    /** Whether this playlist is pinned to the top of the list. */
    pinned?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** Set to true to soft-delete the playlist. */
    deleted?: boolean
    /** JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them. */
    filters?: unknown
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
    readonly recordings_counts: SessionRecordingPlaylistApiRecordingsCounts
    /** Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.
     *
     * * `collection` - Collection
     * * `filters` - Filters */
    type?: SessionRecordingPlaylistPlaylistTypeEnumApi | null
    /** Return whether this is a synthetic playlist */
    readonly is_synthetic: boolean
    _create_in_folder?: string
    /** How the PostHog app created the playlist, for product analytics. Not stored.
     *
     * * `new` - new
     * * `pin` - pin
     * * `duplicate` - duplicate */
    creation_method?: SessionRecordingPlaylistCreationMethodEnumApi
}

export interface PaginatedSessionRecordingPlaylistListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SessionRecordingPlaylistApi[]
}

export type PatchedSessionRecordingPlaylistApiRecordingsCounts = {
    [key: string]: { [key: string]: number | boolean | null }
}

export interface PatchedSessionRecordingPlaylistApi {
    readonly id?: number
    readonly short_id?: string
    /**
     * Human-readable name for the playlist.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    derived_name?: string | null
    /** Optional description of the playlist's purpose or contents. */
    description?: string
    /** Whether this playlist is pinned to the top of the list. */
    pinned?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** Set to true to soft-delete the playlist. */
    deleted?: boolean
    /** JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them. */
    filters?: unknown
    readonly last_modified_at?: string
    readonly last_modified_by?: UserBasicApi
    readonly recordings_counts?: PatchedSessionRecordingPlaylistApiRecordingsCounts
    /** Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.
     *
     * * `collection` - Collection
     * * `filters` - Filters */
    type?: SessionRecordingPlaylistPlaylistTypeEnumApi | null
    /** Return whether this is a synthetic playlist */
    readonly is_synthetic?: boolean
    _create_in_folder?: string
    /** How the PostHog app created the playlist, for product analytics. Not stored.
     *
     * * `new` - new
     * * `pin` - pin
     * * `duplicate` - duplicate */
    creation_method?: SessionRecordingPlaylistCreationMethodEnumApi
}

export interface MinimalPersonApi {
    /** Numeric person ID. */
    readonly id: number
    /** Display name derived from person properties (email, name, or username). */
    readonly name: string
    readonly distinct_ids: readonly string[]
    /** Key-value map of person properties set via $set and $set_once operations. */
    properties?: unknown
    /** When this person was first seen (ISO 8601). */
    readonly created_at: string
    /** Unique identifier (UUID) for this person. */
    readonly uuid: string
    /**
     * Timestamp of the last event from this person, or null.
     * @nullable
     */
    readonly last_seen_at: string | null
}

export type SessionRecordingApiExternalReferencesItem = { [key: string]: unknown }

export interface SessionRecordingApi {
    readonly id: string
    /** @nullable */
    readonly distinct_id: string | null
    readonly viewed: boolean
    readonly viewers: readonly string[]
    readonly recording_duration: number
    /** @nullable */
    readonly active_seconds: number | null
    /** @nullable */
    readonly inactive_seconds: number | null
    /** @nullable */
    readonly start_time: string | null
    /** @nullable */
    readonly end_time: string | null
    /** @nullable */
    readonly click_count: number | null
    /** @nullable */
    readonly keypress_count: number | null
    /** @nullable */
    readonly mouse_activity_count: number | null
    /** @nullable */
    readonly console_log_count: number | null
    /** @nullable */
    readonly console_warn_count: number | null
    /** @nullable */
    readonly console_error_count: number | null
    /** @nullable */
    readonly start_url: string | null
    person?: MinimalPersonApi
    /** @nullable */
    readonly retention_period_days: number | null
    /** @nullable */
    readonly expiry_time: string | null
    /** @nullable */
    readonly recording_ttl: number | null
    /** @nullable */
    readonly snapshot_source: string | null
    /** @nullable */
    readonly snapshot_library: string | null
    readonly ongoing: boolean
    /** @nullable */
    readonly activity_score: number | null
    /** Load external references (linked issues) for this recording */
    readonly external_references: readonly SessionRecordingApiExternalReferencesItem[]
    /** Whether this recording matched the filters of the listing query that returned it. False only when a recording requested via session_recording_id was included despite not matching the filters. */
    readonly matches_filters: boolean
    /**
     * Total stored size of the recording's snapshot data in bytes. Only populated when the recording's metadata is loaded, e.g. on retrieve; null in list responses.
     * @nullable
     */
    readonly total_size: number | null
    /**
     * Number of captured rrweb events in the recording. Only populated when the recording's metadata is loaded, e.g. on retrieve; null in list responses.
     * @nullable
     */
    readonly event_count: number | null
}

export interface PaginatedSessionRecordingListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SessionRecordingApi[]
}

export type PatchedSessionRecordingApiExternalReferencesItem = { [key: string]: unknown }

export interface PatchedSessionRecordingApi {
    readonly id?: string
    /** @nullable */
    readonly distinct_id?: string | null
    readonly viewed?: boolean
    readonly viewers?: readonly string[]
    readonly recording_duration?: number
    /** @nullable */
    readonly active_seconds?: number | null
    /** @nullable */
    readonly inactive_seconds?: number | null
    /** @nullable */
    readonly start_time?: string | null
    /** @nullable */
    readonly end_time?: string | null
    /** @nullable */
    readonly click_count?: number | null
    /** @nullable */
    readonly keypress_count?: number | null
    /** @nullable */
    readonly mouse_activity_count?: number | null
    /** @nullable */
    readonly console_log_count?: number | null
    /** @nullable */
    readonly console_warn_count?: number | null
    /** @nullable */
    readonly console_error_count?: number | null
    /** @nullable */
    readonly start_url?: string | null
    person?: MinimalPersonApi
    /** @nullable */
    readonly retention_period_days?: number | null
    /** @nullable */
    readonly expiry_time?: string | null
    /** @nullable */
    readonly recording_ttl?: number | null
    /** @nullable */
    readonly snapshot_source?: string | null
    /** @nullable */
    readonly snapshot_library?: string | null
    readonly ongoing?: boolean
    /** @nullable */
    readonly activity_score?: number | null
    /** Load external references (linked issues) for this recording */
    readonly external_references?: readonly PatchedSessionRecordingApiExternalReferencesItem[]
    /** Whether this recording matched the filters of the listing query that returned it. False only when a recording requested via session_recording_id was included despite not matching the filters. */
    readonly matches_filters?: boolean
    /**
     * Total stored size of the recording's snapshot data in bytes. Only populated when the recording's metadata is loaded, e.g. on retrieve; null in list responses.
     * @nullable
     */
    readonly total_size?: number | null
    /**
     * Number of captured rrweb events in the recording. Only populated when the recording's metadata is loaded, e.g. on retrieve; null in list responses.
     * @nullable
     */
    readonly event_count?: number | null
}

/**
 * * `info` - Info
 * * `warn` - Warn
 * * `error` - Error
 */
export type ConsoleLogLevelEnumApi = (typeof ConsoleLogLevelEnumApi)[keyof typeof ConsoleLogLevelEnumApi]

export const ConsoleLogLevelEnumApi = {
    Info: 'info',
    Warn: 'warn',
    Error: 'error',
} as const

export interface SessionRecordingConsoleLogEntryApi {
    /** When the browser logged the message. */
    timestamp: string
    /** Console level of the message.
     *
     * * `info` - Info
     * * `warn` - Warn
     * * `error` - Error */
    level: ConsoleLogLevelEnumApi
    /** The logged text. String arguments are joined with spaces, and non-string arguments are left out. Cut to 3000 characters. */
    message: string
    /** True when the message was cut to fit the length limit. */
    truncated: boolean
}

export interface SessionRecordingConsoleLogsResponseApi {
    /** Console log entries in chronological order. */
    results: SessionRecordingConsoleLogEntryApi[]
    /** True when more entries exist after this page. */
    has_more: boolean
    /** Whether the project captures console logs now. When false, an empty result means that nothing was captured, not that the session had no console output. */
    console_log_capture_enabled: boolean
    /** True when the recording started longer ago than the console log retention period. The recording can still exist after its console log entries are deleted. Entries expire one at a time, so a recording close to the retention period can already miss its earliest entries while this is false. */
    logs_expired: boolean
}

export interface SessionRecordingBulkDeleteRequestApi {
    /**
     * Session IDs of the recordings to delete (max 100 per call).
     * @minItems 1
     * @maxItems 100
     */
    session_recording_ids: string[]
    /**
     * Earliest start time of the recordings, as an ISO date or a relative offset like '-30d'. Providing this narrows the lookup and speeds up the request; defaults to the project's recording retention period.
     * @nullable
     */
    date_from?: string | null
}

export interface SessionRecordingBulkDeleteResponseApi {
    /** True when no deletion attempt failed. IDs that were not found, or that the caller lacks edit access to, are skipped rather than failed — compare deleted_count to total_requested to detect skips. */
    success: boolean
    /** Number of recordings that were deleted. */
    deleted_count: number
    /** Number of session recording IDs in the request. */
    total_requested: number
    /** Session IDs that were found but could not be deleted. These can be retried. */
    failed_ids: string[]
}

export type SessionRecordingPlaylistsListParams = {
    created_by?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    short_id?: string
}

export type SessionRecordingsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type SessionRecordingsConsoleLogsRetrieveParams = {
    /**
     * Only return entries at or after this ISO 8601 timestamp. The results never extend outside the recording's own start and end time.
     */
    after?: string
    /**
     * Only return entries at or before this ISO 8601 timestamp. The results never extend outside the recording's own start and end time.
     */
    before?: string
    /**
     * Only return entries at this level. Omit to return every level.
     *
     * * `info` - Info
     * * `warn` - Warn
     * * `error` - Error
     * @minLength 1
     */
    level?: SessionRecordingsConsoleLogsRetrieveLevel
    /**
     * Maximum number of entries to return (1-500, default 100).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of entries to skip. Use with `limit` to page through a long recording.
     * @minimum 0
     */
    offset?: number
}

export type SessionRecordingsConsoleLogsRetrieveLevel =
    (typeof SessionRecordingsConsoleLogsRetrieveLevel)[keyof typeof SessionRecordingsConsoleLogsRetrieveLevel]

export const SessionRecordingsConsoleLogsRetrieveLevel = {
    Info: 'info',
    Warn: 'warn',
    Error: 'error',
} as const
