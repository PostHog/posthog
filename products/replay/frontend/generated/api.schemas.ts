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
 * * `collection` - Collection
 * `filters` - Filters
 */

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SessionRecordingPlaylistTypeEnumApi = {
    collection: 'collection',
    filters: 'filters',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const NullEnumApi = {} as const

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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RoleAtOrganizationEnumApi = {
    engineering: 'engineering',
    data: 'data',
    product: 'product',
    founder: 'founder',
    leadership: 'leadership',
    marketing: 'marketing',
    sales: 'sales',
    other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BlankEnumApi = {
    '': '',
} as const

export type SessionRecordingPlaylistTypeEnumApi =
    (typeof SessionRecordingPlaylistTypeEnumApi)[keyof typeof SessionRecordingPlaylistTypeEnumApi]

export interface PaginatedSessionRecordingPlaylistListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SessionRecordingPlaylistApi[]
}

export type SessionRecordingPlaylistApiRecordingsCounts = { [key: string]: { [key: string]: number | boolean | null } }

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const SessionRecordingPlaylistApiType = { ...SessionRecordingPlaylistTypeEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type SessionRecordingPlaylistApiType =
    | (typeof SessionRecordingPlaylistApiType)[keyof typeof SessionRecordingPlaylistApiType]
    | null

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
    /** @nullable */
    readonly type: SessionRecordingPlaylistApiType
    /** Return whether this is a synthetic playlist */
    readonly is_synthetic: boolean
    _create_in_folder?: string
}

export type PatchedSessionRecordingPlaylistApiRecordingsCounts = {
    [key: string]: { [key: string]: number | boolean | null }
}

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PatchedSessionRecordingPlaylistApiType = {
    ...SessionRecordingPlaylistTypeEnumApi,
    ...NullEnumApi,
} as const
/**
 * @nullable
 */
export type PatchedSessionRecordingPlaylistApiType =
    | (typeof PatchedSessionRecordingPlaylistApiType)[keyof typeof PatchedSessionRecordingPlaylistApiType]
    | null

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
    /** @nullable */
    readonly type?: PatchedSessionRecordingPlaylistApiType
    /** Return whether this is a synthetic playlist */
    readonly is_synthetic?: boolean
    _create_in_folder?: string
}

export interface PaginatedSessionRecordingListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SessionRecordingApi[]
}

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
    readonly ongoing: boolean
    /** @nullable */
    readonly activity_score: number | null
}

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
    readonly ongoing?: boolean
    /** @nullable */
    readonly activity_score?: number | null
}

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const UserBasicApiRoleAtOrganization = { ...RoleAtOrganizationEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type UserBasicApiRoleAtOrganization =
    | (typeof UserBasicApiRoleAtOrganization)[keyof typeof UserBasicApiRoleAtOrganization]
    | null

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
    /** @nullable */
    role_at_organization?: UserBasicApiRoleAtOrganization
}

export interface MinimalPersonApi {
    readonly id: number
    readonly name: string
    readonly distinct_ids: string
    properties?: unknown
    readonly created_at: string
    readonly uuid: string
}

export type EnvironmentsSessionRecordingPlaylistsListParams = {
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

export type EnvironmentsSessionRecordingsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
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
