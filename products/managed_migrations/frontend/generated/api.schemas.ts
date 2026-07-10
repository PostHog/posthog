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
 * * `completed` - Completed
 * * `failed` - Failed
 * * `paused` - Paused
 * * `running` - Running
 */
export type BatchImportStatusEnumApi = (typeof BatchImportStatusEnumApi)[keyof typeof BatchImportStatusEnumApi]

export const BatchImportStatusEnumApi = {
    Completed: 'completed',
    Failed: 'failed',
    Paused: 'paused',
    Running: 'running',
} as const

export type DisplayStatusEnumApi = (typeof DisplayStatusEnumApi)[keyof typeof DisplayStatusEnumApi]

export const DisplayStatusEnumApi = {
    WaitingToStart: 'waiting_to_start',
    Running: 'running',
    Paused: 'paused',
    Failed: 'failed',
    Completed: 'completed',
} as const

export interface BatchImportPartsProgressApi {
    /** Number of finished parts (a part is done when its committed byte offset has reached its known total size). */
    done: number
    /** Total number of parts the worker has planned for this import. */
    total: number
    /**
     * Key (file/date-range identifier) of the first unfinished part - the one in flight or next up. Null when all parts are done or the worker has not started.
     * @nullable
     */
    inflight_key: string | null
    /**
     * Committed byte offset (decompressed) within the in-flight part. Null when there is no in-flight part.
     * @nullable
     */
    inflight_offset: number | null
    /**
     * Total decompressed size in bytes of the in-flight part, or null if the worker has not measured it yet.
     * @nullable
     */
    inflight_total_size: number | null
}

/**
 * Compact cross-team diagnostics view of a batch import job for PostHog support staff.
 *
 * Excludes the raw `state` / `import_config` blobs (see the detail serializer) and never
 * exposes the encrypted `secrets` column.
 */
export interface BatchImportSupportListApi {
    /** UUID of the batch import job. */
    readonly id: string
    /** ID of the team (project) the import belongs to. */
    team_id: number
    /** Name of the team the import belongs to. */
    team_name: string
    /** Raw persisted status of the job.
     *
     * * `completed` - Completed
     * * `failed` - Failed
     * * `paused` - Paused
     * * `running` - Running */
    status?: BatchImportStatusEnumApi
    /** Effective status: 'waiting_to_start' when the job is running but no worker has claimed it yet (lease_id is null), otherwise the raw status. */
    readonly display_status: DisplayStatusEnumApi
    /**
     * Developer-facing status message written by the worker or an operator - the primary debugging signal. Not shown to the customer.
     * @nullable
     */
    status_message?: string | null
    /**
     * Customer-facing status message shown in the PostHog UI.
     * @nullable
     */
    display_status_message?: string | null
    /** Worker part progress summary derived from the raw state blob. */
    readonly parts_progress: BatchImportPartsProgressApi
    /** Source the job imports from (e.g. s3, mixpanel, amplitude, urls, folder), or 'unknown' if unset. */
    readonly source_type: string
    /** Format of the source events (e.g. mixpanel, amplitude, captured), or 'unknown' if unset. */
    readonly content_type: string
    /**
     * Start of the source date range for date-range sources (Mixpanel/Amplitude), else null.
     * @nullable
     */
    readonly source_start_date: string | null
    /**
     * End of the source date range for date-range sources (Mixpanel/Amplitude), else null.
     * @nullable
     */
    readonly source_end_date: string | null
    /**
     * Where imported events are written (normally 'capture'; 'kafka'/'noop' for internal use), or null if unset.
     * @nullable
     */
    readonly sink_type: string | null
    /**
     * Configured sink send rate in events per second, or null if unset.
     * @nullable
     */
    readonly sink_send_rate: number | null
    /**
     * Lease token of the worker currently holding the job, or null when unclaimed. Claims lease for 30 minutes; the running heartbeat renews for 5 minutes.
     * @nullable
     */
    lease_id?: string | null
    /**
     * When the current worker lease expires.
     * @nullable
     */
    leased_until?: string | null
    /** True when the job holds a lease whose expiry is in the past. On a running job this means the worker died or the row is claimable again; the next poll can re-claim it. */
    readonly lease_expired: boolean
    /**
     * Consecutive transient-failure retries so far (0 = healthy).
     * @minimum -2147483648
     * @maximum 2147483647
     */
    backoff_attempt?: number
    /**
     * When the worker will retry after a transient failure. A future value means the job is in a retry loop, not stuck.
     * @nullable
     */
    backoff_until?: string | null
    /**
     * ID of the user who created the import, if any.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    created_by_id?: number | null
    /** When the import was created. */
    readonly created_at: string
    /** Last write to the row - the worker heartbeats this while processing. */
    readonly updated_at: string
}

export interface PaginatedBatchImportSupportListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BatchImportSupportListApi[]
}

/**
 * Raw worker progress blob: {'parts': [{'key', 'current_offset', 'total_size'}]}. A part is done when current_offset >= total_size; parts are processed in order.
 * @nullable
 */
export type BatchImportSupportDetailApiState = { [key: string]: unknown } | null

/**
 * Source/format/sink configuration of the job. References secrets by key name only; secret values are never returned.
 * @nullable
 */
export type BatchImportSupportDetailApiImportConfig = { [key: string]: unknown } | null

/**
 * Full diagnostics view: adds the raw worker `state` and `import_config` blobs.
 *
 * `import_config` holds secret key *names* only - secret values live exclusively in the
 * encrypted `secrets` column, which no support serializer exposes.
 */
export interface BatchImportSupportDetailApi {
    /** UUID of the batch import job. */
    readonly id: string
    /** ID of the team (project) the import belongs to. */
    team_id: number
    /** Name of the team the import belongs to. */
    team_name: string
    /** Raw persisted status of the job.
     *
     * * `completed` - Completed
     * * `failed` - Failed
     * * `paused` - Paused
     * * `running` - Running */
    status?: BatchImportStatusEnumApi
    /** Effective status: 'waiting_to_start' when the job is running but no worker has claimed it yet (lease_id is null), otherwise the raw status. */
    readonly display_status: DisplayStatusEnumApi
    /**
     * Developer-facing status message written by the worker or an operator - the primary debugging signal. Not shown to the customer.
     * @nullable
     */
    status_message?: string | null
    /**
     * Customer-facing status message shown in the PostHog UI.
     * @nullable
     */
    display_status_message?: string | null
    /** Worker part progress summary derived from the raw state blob. */
    readonly parts_progress: BatchImportPartsProgressApi
    /** Source the job imports from (e.g. s3, mixpanel, amplitude, urls, folder), or 'unknown' if unset. */
    readonly source_type: string
    /** Format of the source events (e.g. mixpanel, amplitude, captured), or 'unknown' if unset. */
    readonly content_type: string
    /**
     * Start of the source date range for date-range sources (Mixpanel/Amplitude), else null.
     * @nullable
     */
    readonly source_start_date: string | null
    /**
     * End of the source date range for date-range sources (Mixpanel/Amplitude), else null.
     * @nullable
     */
    readonly source_end_date: string | null
    /**
     * Where imported events are written (normally 'capture'; 'kafka'/'noop' for internal use), or null if unset.
     * @nullable
     */
    readonly sink_type: string | null
    /**
     * Configured sink send rate in events per second, or null if unset.
     * @nullable
     */
    readonly sink_send_rate: number | null
    /**
     * Lease token of the worker currently holding the job, or null when unclaimed. Claims lease for 30 minutes; the running heartbeat renews for 5 minutes.
     * @nullable
     */
    lease_id?: string | null
    /**
     * When the current worker lease expires.
     * @nullable
     */
    leased_until?: string | null
    /** True when the job holds a lease whose expiry is in the past. On a running job this means the worker died or the row is claimable again; the next poll can re-claim it. */
    readonly lease_expired: boolean
    /**
     * Consecutive transient-failure retries so far (0 = healthy).
     * @minimum -2147483648
     * @maximum 2147483647
     */
    backoff_attempt?: number
    /**
     * When the worker will retry after a transient failure. A future value means the job is in a retry loop, not stuck.
     * @nullable
     */
    backoff_until?: string | null
    /**
     * ID of the user who created the import, if any.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    created_by_id?: number | null
    /** When the import was created. */
    readonly created_at: string
    /** Last write to the row - the worker heartbeats this while processing. */
    readonly updated_at: string
    /**
     * Raw worker progress blob: {'parts': [{'key', 'current_offset', 'total_size'}]}. A part is done when current_offset >= total_size; parts are processed in order.
     * @nullable
     */
    readonly state: BatchImportSupportDetailApiState
    /**
     * Source/format/sink configuration of the job. References secrets by key name only; secret values are never returned.
     * @nullable
     */
    readonly import_config: BatchImportSupportDetailApiImportConfig
    /**
     * Email of the user who created the import, if known.
     * @nullable
     */
    readonly created_by_email: string | null
}

/**
 * @nullable
 */
export type BatchImportApiCreatedBy = { [key: string]: unknown } | null

/**
 * Serializer for BatchImport model
 */
export interface BatchImportApi {
    readonly id: string
    readonly team_id: number
    readonly created_at: string
    readonly updated_at: string
    readonly state: unknown
    /** @nullable */
    readonly created_by: BatchImportApiCreatedBy
    readonly status: BatchImportStatusEnumApi
    /** @nullable */
    readonly display_status_message: string | null
    readonly import_config: unknown
}

export interface PaginatedBatchImportListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BatchImportApi[]
}

/**
 * @nullable
 */
export type PatchedBatchImportApiCreatedBy = { [key: string]: unknown } | null

/**
 * Serializer for BatchImport model
 */
export interface PatchedBatchImportApi {
    readonly id?: string
    readonly team_id?: number
    readonly created_at?: string
    readonly updated_at?: string
    readonly state?: unknown
    /** @nullable */
    readonly created_by?: PatchedBatchImportApiCreatedBy
    readonly status?: BatchImportStatusEnumApi
    /** @nullable */
    readonly display_status_message?: string | null
    readonly import_config?: unknown
}

export type ManagedMigrationsSupportListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
    /**
     * A search term.
     */
    search?: string
    /**
     * * `completed` - Completed
     * * `failed` - Failed
     * * `paused` - Paused
     * * `running` - Running
     */
    status?: ManagedMigrationsSupportListStatus
    team_id?: number
}

export type ManagedMigrationsSupportListStatus =
    (typeof ManagedMigrationsSupportListStatus)[keyof typeof ManagedMigrationsSupportListStatus]

export const ManagedMigrationsSupportListStatus = {
    Completed: 'completed',
    Failed: 'failed',
    Paused: 'paused',
    Running: 'running',
} as const

export type ManagedMigrationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
    /**
     * A search term.
     */
    search?: string
    /**
     * * `completed` - Completed
     * * `failed` - Failed
     * * `paused` - Paused
     * * `running` - Running
     */
    status?: ManagedMigrationsListStatus
}

export type ManagedMigrationsListStatus = (typeof ManagedMigrationsListStatus)[keyof typeof ManagedMigrationsListStatus]

export const ManagedMigrationsListStatus = {
    Completed: 'completed',
    Failed: 'failed',
    Paused: 'paused',
    Running: 'running',
} as const
