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

export interface AppSummaryContractApi {
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

export interface PaginatedAppSummaryContractListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AppSummaryContractApi[]
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

export interface AppSandboxContractApi {
    status: string
    restart_count: number
    last_error: string
    /** @nullable */
    started_at: string | null
    /** @nullable */
    last_activity_at: string | null
    /** @nullable */
    version_number: number | null
}

export interface AppContractApi {
    /** User who created this app. */
    created_by?: StreamlitAppUserInfoApi | null
    /** Currently active version, or null if none uploaded yet. */
    active_version?: AppVersionContractApi | null
    /** Current sandbox state, or null if the app has never started. */
    sandbox?: AppSandboxContractApi | null
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

/**
 * Extra text files to ship next to app.py, keyed by project-relative path (for example 'utils.py' or 'data/config.json'), each as plain text (max 1 MB).
 */
export type CreateVersionFromSourceInputApiFiles = { [key: string]: string }

/**
 * Extra binary files to ship next to app.py, keyed by project-relative path (for example 'data/events.parquet'), each as standard base64 text.
 */
export type CreateVersionFromSourceInputApiAssets = { [key: string]: string }

export interface CreateVersionFromSourceInputApi {
    /**
     * Full Python source for the Streamlit app's root app.py file, as free text (max 1 MB). Becomes a new version and is set as the active version.
     * @maxLength 1048576
     */
    source: string
    /** Extra text files to ship next to app.py, keyed by project-relative path (for example 'utils.py' or 'data/config.json'), each as plain text (max 1 MB). */
    files?: CreateVersionFromSourceInputApiFiles
    /** Extra binary files to ship next to app.py, keyed by project-relative path (for example 'data/events.parquet'), each as standard base64 text. */
    assets?: CreateVersionFromSourceInputApiAssets
}

/**
 * New text files keyed by project-relative path, each value the file's full text (max 1 MB). The path must not exist in the base version.
 */
export type EditVersionSourceInputApiCreateFiles = { [key: string]: string }

export interface SourceTextEditApi {
    /** Exact text to find in the file. Must match exactly once. */
    old: string
    /** Replacement text. */
    new: string
}

export interface SourceFileEditApi {
    /** Path of an existing text file in the base version, for example 'app.py'. */
    path: string
    /** Find-and-replace operations, applied in order to the file's text. At most 100 edits per request across all files. */
    edits: SourceTextEditApi[]
}

export interface EditVersionSourceInputApi {
    /**
     * Version number that the changes apply to. Must be the latest version of the app, otherwise the request fails with 409 and returns the current version number.
     * @minimum 1
     */
    base_version: number
    /** Exact text edits to existing text files. Files that no change touches stay byte-for-byte the same. */
    file_edits?: SourceFileEditApi[]
    /** New text files keyed by project-relative path, each value the file's full text (max 1 MB). The path must not exist in the base version. */
    create_files?: EditVersionSourceInputApiCreateFiles
    /** Paths of files to remove from the base version. app.py cannot be removed. */
    delete_files?: string[]
}

export interface SourceEditErrorApi {
    /** Why the change could not be applied. */
    detail: string
    /**
     * Path of the file that caused the error, if any.
     * @nullable
     */
    path: string | null
    /**
     * Zero-based index of the failed edit inside that file's edits, if any.
     * @nullable
     */
    edit_index: number | null
}

export interface VersionConflictApi {
    /** Why the change was refused. */
    detail: string
    /** Latest version number of the app. Read it and retry. */
    current_version: number
}

export interface AppSourceFileContractApi {
    /** Project-relative path of the file, for example 'app.py' or 'pages/1_Overview.py'. */
    path: string
    /** File size in bytes. */
    size: number
    /** SHA-256 hash of the file bytes, as hex. */
    sha256: string
    /** MIME type guessed from the file extension. */
    content_type: string
    /** True when the file is not UTF-8 text. Binary content is never inlined. */
    is_binary: boolean
    /**
     * Full text of the file. Null for binary files and for files that the paths filter excludes.
     * @nullable
     */
    content: string | null
}

export interface AppVersionSourceContractApi {
    /** Version number that this source belongs to. */
    version_number: number
    /** Every file in the version, sorted by path. The manifest always lists all files. */
    files: AppSourceFileContractApi[]
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

export type StreamlitAppsSourceRetrieveParams = {
    /**
     * Comma-separated file paths whose content to return, for example 'app.py,utils.py'. Other files appear in the manifest without content. Defaults to all text files.
     * @minLength 1
     */
    paths?: string
    /**
     * Version number to read. Defaults to the active version.
     * @minimum 1
     */
    version_number?: number
}
