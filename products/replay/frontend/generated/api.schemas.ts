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
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

/**
 * * `collection` - Collection
 * `filters` - Filters
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

* `collection` - Collection
* `filters` - Filters */
    type?: SessionRecordingPlaylistTypeEnumApi | NullEnumApi | null
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

* `collection` - Collection
* `filters` - Filters */
    type?: SessionRecordingPlaylistTypeEnumApi | NullEnumApi | null
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
