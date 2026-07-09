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
 * @nullable
 */
export type StreamlitAppUserInfoApiHedgehogConfig = { [key: string]: unknown } | null

export interface StreamlitAppUserInfoApi {
    id: number
    uuid: string
    /** @nullable */
    distinct_id: string | null
    first_name: string
    last_name: string
    email: string
    /** @nullable */
    is_email_verified: boolean | null
    /** @nullable */
    hedgehog_config: StreamlitAppUserInfoApiHedgehogConfig
    /** @nullable */
    role_at_organization: string | null
}

export interface AppContractApi {
    /** User who created this app. */
    created_by?: StreamlitAppUserInfoApi | null
    id: string
    short_id: string
    name: string
    description: string
    cpu_cores: number
    memory_gb: number
    status: string
    created_at: string
    updated_at: string
}

export interface PaginatedAppContractListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AppContractApi[]
}

export interface CreateAppInputApi {
    /** Name of the app. */
    name: string
    /** Optional description of the app. */
    description?: string
    /** CPU cores allocated to the sandbox. */
    cpu_cores?: number
    /** Memory in GB allocated to the sandbox. */
    memory_gb?: number
}

export interface UpdateAppInputApi {
    /** New name for the app. */
    name?: string
    /** New description for the app. */
    description?: string
    /** New CPU core allocation for the sandbox. */
    cpu_cores?: number
    /** New memory (GB) allocation for the sandbox. */
    memory_gb?: number
}

export interface PatchedUpdateAppInputApi {
    /** New name for the app. */
    name?: string
    /** New description for the app. */
    description?: string
    /** New CPU core allocation for the sandbox. */
    cpu_cores?: number
    /** New memory (GB) allocation for the sandbox. */
    memory_gb?: number
}

export interface ActivateVersionRequestApi {
    /** Version number to activate. Must reference an existing version of this app. */
    version_number: number
}

export interface AppVersionContractApi {
    /** User who uploaded this version. */
    created_by?: StreamlitAppUserInfoApi | null
    id: string
    version_number: number
    zip_hash: string
    /** @nullable */
    snapshot_id: string | null
    created_at: string
}

export interface ActivateVersionResponseApi {
    /** The version that is now active for the app. */
    active_version: AppVersionContractApi
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
    results: AppVersionContractApi[]
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
