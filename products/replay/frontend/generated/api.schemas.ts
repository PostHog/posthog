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
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    derived_name?: string | null
    description?: string
    pinned?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    deleted?: boolean
    filters?: unknown
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
    readonly recordings_counts: SessionRecordingPlaylistApiRecordingsCounts
    readonly type: SessionRecordingPlaylistTypeEnumApi | NullEnumApi | null
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
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    derived_name?: string | null
    description?: string
    pinned?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    deleted?: boolean
    filters?: unknown
    readonly last_modified_at?: string
    readonly last_modified_by?: UserBasicApi
    readonly recordings_counts?: PatchedSessionRecordingPlaylistApiRecordingsCounts
    readonly type?: SessionRecordingPlaylistTypeEnumApi | NullEnumApi | null
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
    readonly expiry_time: string
    readonly recording_ttl: string
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

/**
 * Response serializer for the session recording list endpoint.
 */
export interface SessionRecordingListResponseApi {
    results: SessionRecordingApi[]
    has_next: boolean
    version: number
    /**
     * Cursor for fetching the next page of results.
     * @nullable
     */
    next_cursor?: string | null
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
    readonly expiry_time?: string
    readonly recording_ttl?: string
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
     * JSON array of action filters. Similar to events but references saved actions by ID.
     * @minLength 1
     */
    actions?: string
    /**
     * JSON array of console log entry filters. Example: '[{"key":"level","type":"log_entry","value":["error"],"operator":"exact"}]'
     * @minLength 1
     */
    console_log_filters?: string
    /**
     * Start date for the search range. Relative: '-3d', '-7d', '-24h'. Absolute: '2024-01-01'. Defaults to '-3d'.
     * @minLength 1
     */
    date_from?: string
    /**
     * End date for the search range. Null means 'now'. Absolute: '2024-01-15'.
     * @minLength 1
     */
    date_to?: string
    /**
     * JSON array of distinct IDs. Example: '["user@example.com"]'
     * @minLength 1
     */
    distinct_ids?: string
    /**
     * JSON array of event filters. Matches recordings containing at least one matching event. Example: '[{"id":"$pageview","type":"events","properties":[{"key":"$current_url","type":"event","value":"/pricing","operator":"icontains"}]}]'
     * @minLength 1
     */
    events?: string
    /**
     * Exclude internal/test users. Defaults to false.
     */
    filter_test_accounts?: boolean
    /**
     * Maximum number of recordings to return per page.
     */
    limit?: number
    /**
     * Number of recordings to skip for pagination.
     */
    offset?: number
    /**
 * Logical operator to combine property filters. Defaults to 'AND'.

* `AND` - AND
* `OR` - OR
 * @minLength 1
 */
    operand?: SessionRecordingsListOperand
    /**
 * Field to order recordings by. Defaults to 'start_time'.

* `start_time` - start_time
* `duration` - duration
* `recording_duration` - recording_duration
* `console_error_count` - console_error_count
* `active_seconds` - active_seconds
* `inactive_seconds` - inactive_seconds
* `click_count` - click_count
* `keypress_count` - keypress_count
* `mouse_activity_count` - mouse_activity_count
* `activity_score` - activity_score
* `recording_ttl` - recording_ttl
 * @minLength 1
 */
    order?: SessionRecordingsListOrder
    /**
 * Sort direction. Defaults to 'DESC'.

* `ASC` - ASC
* `DESC` - DESC
 * @minLength 1
 */
    order_direction?: SessionRecordingsListOrderDirection
    /**
     * Filter recordings by a specific person UUID.
     * @minLength 1
     */
    person_uuid?: string
    /**
     * JSON array of property filters for person, session, event, recording, or cohort properties. Example: '[{"key":"$browser","type":"person","value":["Chrome"],"operator":"exact"}]'. Supported types: person, session, event, recording, cohort, group, hogql.
     * @minLength 1
     */
    properties?: string
    /**
     * JSON array of session IDs to filter by. Example: '["session-abc","session-def"]'
     * @minLength 1
     */
    session_ids?: string
}

export type SessionRecordingsListOperand =
    (typeof SessionRecordingsListOperand)[keyof typeof SessionRecordingsListOperand]

export const SessionRecordingsListOperand = {
    And: 'AND',
    Or: 'OR',
} as const

export type SessionRecordingsListOrder = (typeof SessionRecordingsListOrder)[keyof typeof SessionRecordingsListOrder]

export const SessionRecordingsListOrder = {
    StartTime: 'start_time',
    Duration: 'duration',
    RecordingDuration: 'recording_duration',
    ConsoleErrorCount: 'console_error_count',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
    ClickCount: 'click_count',
    KeypressCount: 'keypress_count',
    MouseActivityCount: 'mouse_activity_count',
    ActivityScore: 'activity_score',
    RecordingTtl: 'recording_ttl',
} as const

export type SessionRecordingsListOrderDirection =
    (typeof SessionRecordingsListOrderDirection)[keyof typeof SessionRecordingsListOrderDirection]

export const SessionRecordingsListOrderDirection = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const
