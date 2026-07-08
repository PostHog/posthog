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

export interface StreamlitAppMinimalApi {
    readonly id: string
    readonly short_id: string
    readonly name: string
    readonly description: string
    readonly cpu_cores: number
    readonly memory_gb: number
    readonly status: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedStreamlitAppMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: StreamlitAppMinimalApi[]
}

export interface StreamlitAppVersionApi {
    readonly id: string
    readonly version_number: number
    readonly zip_hash: string
    /** @nullable */
    readonly snapshot_id: string | null
    readonly created_by: UserBasicApi
    readonly created_at: string
}

/**
 * * `starting` - Starting
 * * `running` - Running
 * * `stopping` - Stopping
 * * `stopped` - Stopped
 * * `error` - Error
 */
export type StreamlitAppSandboxStatusEnumApi =
    (typeof StreamlitAppSandboxStatusEnumApi)[keyof typeof StreamlitAppSandboxStatusEnumApi]

export const StreamlitAppSandboxStatusEnumApi = {
    Starting: 'starting',
    Running: 'running',
    Stopping: 'stopping',
    Stopped: 'stopped',
    Error: 'error',
} as const

export interface StreamlitAppSandboxApi {
    readonly status: StreamlitAppSandboxStatusEnumApi
    readonly restart_count: number
    readonly last_error: string
    /** @nullable */
    readonly started_at: string | null
    /** @nullable */
    readonly last_activity_at: string | null
    readonly version_number: number
}

export interface StreamlitAppApi {
    readonly id: string
    readonly short_id: string
    /** @maxLength 255 */
    name: string
    description?: string
    cpu_cores?: number
    memory_gb?: number
    readonly active_version: StreamlitAppVersionApi
    readonly sandbox: StreamlitAppSandboxApi
    readonly status: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
}

export interface PatchedStreamlitAppApi {
    readonly id?: string
    readonly short_id?: string
    /** @maxLength 255 */
    name?: string
    description?: string
    cpu_cores?: number
    memory_gb?: number
    readonly active_version?: StreamlitAppVersionApi
    readonly sandbox?: StreamlitAppSandboxApi
    readonly status?: string
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
}

export interface ActivateVersionRequestApi {
    /** Version number to activate. Must reference an existing version of this app. */
    version_number: number
}

export interface ActivateVersionResponseApi {
    /** The version that is now active for the app. */
    active_version: StreamlitAppVersionApi
}

export interface StreamlitConnectInfoApi {
    /** Authenticated URL to embed the running app in an iframe. */
    iframe_url: string
    /** Seconds until the embedded session credential expires. */
    expires_in: number
}

export interface StreamlitAppStatusApi {
    /** Sandbox lifecycle status, or 'stopped' when no sandbox exists. */
    status: string
    /** Number of times the app's sandbox has been restarted. */
    restart_count: number
    /** Most recent sandbox error message, empty when there is none. */
    last_error: string
    /**
     * When the current sandbox started, null when stopped.
     * @nullable
     */
    started_at: string | null
    /**
     * Timestamp of the last recorded viewer activity, null when none.
     * @nullable
     */
    last_activity_at: string | null
    /**
     * Version number the running sandbox was booted from.
     * @nullable
     */
    version_number?: number | null
}

export interface UploadVersionRequestApi {
    /** Zip archive containing the Streamlit app sources (max 10 MB). */
    file: string
}

export interface StreamlitAppVersionListApi {
    /** Most recent versions of the app, newest first (capped at 50). */
    results: StreamlitAppVersionApi[]
}

export type StreamlitAppsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
