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
export type SessionRecordingPlaylistTypeEnumApi =
    (typeof SessionRecordingPlaylistTypeEnumApi)[keyof typeof SessionRecordingPlaylistTypeEnumApi]

export const SessionRecordingPlaylistTypeEnumApi = {
    Collection: 'collection',
    Filters: 'filters',
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
    type?: SessionRecordingPlaylistTypeEnumApi | null
    /** Return whether this is a synthetic playlist */
    readonly is_synthetic: boolean
    _create_in_folder?: string
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
    type?: SessionRecordingPlaylistTypeEnumApi | null
    /** Return whether this is a synthetic playlist */
    readonly is_synthetic?: boolean
    _create_in_folder?: string
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

/**
 * Initial goal and session outcome coming from LLM.
 */
export interface OutcomeApi {
    /**
     * @minLength 1
     * @maxLength 10000
     * @nullable
     */
    description?: string | null
    /** @nullable */
    success?: boolean | null
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
    readonly has_summary: boolean
    readonly summary_outcome: OutcomeApi | null
    /** Load external references (linked issues) for this recording */
    readonly external_references: readonly SessionRecordingApiExternalReferencesItem[]
    /** Whether this recording matched the filters of the listing query that returned it. False only when a recording requested via session_recording_id was included despite not matching the filters. */
    readonly matches_filters: boolean
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
    readonly has_summary?: boolean
    readonly summary_outcome?: OutcomeApi | null
    /** Load external references (linked issues) for this recording */
    readonly external_references?: readonly PatchedSessionRecordingApiExternalReferencesItem[]
    /** Whether this recording matched the filters of the listing query that returned it. False only when a recording requested via session_recording_id was included despite not matching the filters. */
    readonly matches_filters?: boolean
}

export interface SessionRecordingBulkDeleteRequestApi {
    /**
     * Session IDs of the recordings to delete (max 20 per call).
     * @minItems 1
     * @maxItems 20
     */
    session_recording_ids: string[]
    /**
     * Earliest start time of the recordings, as an ISO date or a relative offset like '-30d'. Providing this narrows the lookup and speeds up the request; defaults to the project's recording retention period.
     * @nullable
     */
    date_from?: string | null
}

export interface SessionRecordingBulkDeleteResponseApi {
    /** True when every requested recording was deleted or not found. */
    success: boolean
    /** Number of recordings that were deleted. */
    deleted_count: number
    /** Number of session recording IDs in the request. */
    total_requested: number
    /** Session IDs that were found but could not be deleted. These can be retried. */
    failed_ids: string[]
}

export interface SessionSummariesApi {
    /**
     * List of session IDs to summarize (max 300)
     * @minItems 1
     * @maxItems 300
     */
    session_ids: string[]
    /**
     * Optional focus area for the summarization
     * @maxLength 500
     */
    focus_area?: string
}

/**
 * Headline outcome from the summary: `{success: bool, description: string}` or null if the summary did not record one. Useful for quickly classifying a session as success/failure.
 * @nullable
 */
export type SingleSessionSummaryMinimalApiSessionOutcome = {
    readonly success?: boolean
    readonly description?: string
} | null

/**
 * Optional context passed to the summary at generation time (e.g. `focus_area`).
 * @nullable
 */
export type SingleSessionSummaryMinimalApiExtraSummaryContext = {
    readonly focus_area?: string
} | null

/**
 * Lightweight projection for list endpoints — omits the full `summary` JSON (~50 KB per row).
 */
export interface SingleSessionSummaryMinimalApi {
    readonly id: string
    /** Session replay ID */
    readonly session_id: string
    /**
     * Distinct ID of the session's user
     * @nullable
     */
    readonly distinct_id: string | null
    /**
     * Session start time
     * @nullable
     */
    readonly session_start_time: string | null
    /**
     * Session duration in seconds
     * @nullable
     */
    readonly session_duration: number | null
    /**
     * Headline outcome from the summary: `{success: bool, description: string}` or null if the summary did not record one. Useful for quickly classifying a session as success/failure.
     * @nullable
     */
    readonly session_outcome: SingleSessionSummaryMinimalApiSessionOutcome
    /** Number of exception event IDs surfaced by this summary (capped at 100). */
    readonly exception_count: number
    /** True if the summary surfaced any exception events. */
    readonly has_exceptions: boolean
    /**
     * LLM model identifier that generated this summary, if recorded in run metadata.
     * @nullable
     */
    readonly model_used: string | null
    /** True if the summary was produced with video-based visual confirmation (the rasterized-recording path). */
    readonly visual_confirmation: boolean
    /**
     * Optional context passed to the summary at generation time (e.g. `focus_area`).
     * @nullable
     */
    readonly extra_summary_context: SingleSessionSummaryMinimalApiExtraSummaryContext
    readonly created_at: string
    readonly created_by: UserBasicApi | null
}

export interface PaginatedSingleSessionSummaryMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SingleSessionSummaryMinimalApi[]
}

/**
 * Full LLM-generated summary JSON. Contains `segments` (chronological journey segments), `key_actions` (per-segment events with `abandonment` / `confusion` / `exception` flags — the structured source of session-level problems), `segment_outcomes`, and `session_outcome`. Video-based runs additionally include a `sentiment` block.
 */
export type SingleSessionSummaryApiSummary = { [key: string]: unknown }

/**
 * Optional context passed to the summary at generation time (e.g. `focus_area`).
 * @nullable
 */
export type SingleSessionSummaryApiExtraSummaryContext = {
    readonly focus_area?: string
} | null

/**
 * `SessionSummaryRunMeta` — model used, whether video-based visual confirmation was applied, and visual-confirmation event-to-asset mappings.
 * @nullable
 */
export type SingleSessionSummaryApiRunMetadata = { [key: string]: unknown } | null

/**
 * Full session summary, including the generated `summary` JSON content.
 */
export interface SingleSessionSummaryApi {
    readonly id: string
    /** Session replay ID */
    readonly session_id: string
    /**
     * Distinct ID of the session's user
     * @nullable
     */
    readonly distinct_id: string | null
    /**
     * Session start time
     * @nullable
     */
    readonly session_start_time: string | null
    /**
     * Session duration in seconds
     * @nullable
     */
    readonly session_duration: number | null
    /** Full LLM-generated summary JSON. Contains `segments` (chronological journey segments), `key_actions` (per-segment events with `abandonment` / `confusion` / `exception` flags — the structured source of session-level problems), `segment_outcomes`, and `session_outcome`. Video-based runs additionally include a `sentiment` block. */
    readonly summary: SingleSessionSummaryApiSummary
    /** Event IDs (capped at 100) where exceptions occurred during the session — extracted from the summary for searchability. */
    readonly exception_event_ids: readonly string[]
    /**
     * Optional context passed to the summary at generation time (e.g. `focus_area`).
     * @nullable
     */
    readonly extra_summary_context: SingleSessionSummaryApiExtraSummaryContext
    /**
     * `SessionSummaryRunMeta` — model used, whether video-based visual confirmation was applied, and visual-confirmation event-to-asset mappings.
     * @nullable
     */
    readonly run_metadata: SingleSessionSummaryApiRunMetadata
    readonly created_at: string
    readonly created_by: UserBasicApi | null
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

export type SingleSessionSummariesListParams = {
    /**
     * Filter to summaries triggered by a specific user, identified by `User.uuid`.
     */
    created_by?: string
    /**
     * Inclusive lower bound on `created_at`, accepts relative shorthand like `-7d`.
     */
    date_from?: string
    /**
     * Inclusive upper bound on `created_at`, accepts relative shorthand like `-1d`.
     */
    date_to?: string
    /**
     * Filter to summaries for a single user (the session's `distinct_id`).
     */
    distinct_id?: string
    /**
     * When true, only summaries that surfaced one or more exception events; when false, only summaries without exceptions.
     */
    has_exceptions?: boolean
    /**
     * When true, only summaries produced via the video-based visual-confirmation workflow.
     */
    has_visual_confirmation?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Ordering field, defaults to `-created_at` (most recent first). Allowed: `created_at`, `session_start_time`, `session_duration` (prefix with `-` for descending).
     */
    order?: string
    /**
     * Filter by the summary's recorded `session_outcome.success` field. `success` for true, `failure` for false, `unknown` for summaries without an outcome.
     */
    outcome?: SingleSessionSummariesListOutcome
    /**
     * Comma-separated list of session IDs to restrict the result to (uses the `(team, session_id)` index).
     */
    session_ids?: string
}

export type SingleSessionSummariesListOutcome =
    (typeof SingleSessionSummariesListOutcome)[keyof typeof SingleSessionSummariesListOutcome]

export const SingleSessionSummariesListOutcome = {
    Failure: 'failure',
    Success: 'success',
    Unknown: 'unknown',
} as const
