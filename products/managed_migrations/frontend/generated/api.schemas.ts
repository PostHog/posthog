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

/**
 * @nullable
 */
export type BatchImportResponseApiCreatedBy = { [key: string]: unknown } | null

/**
 * Serializer for BatchImport responses that matches frontend expectations
 */
export interface BatchImportResponseApi {
    readonly id: string
    readonly source_type: string
    readonly content_type: string
    status?: BatchImportStatusEnumApi
    readonly display_status: string
    /** @nullable */
    readonly start_date: string | null
    /** @nullable */
    readonly end_date: string | null
    /** @nullable */
    readonly created_by: BatchImportResponseApiCreatedBy
    readonly created_at: string
    /** @nullable */
    status_message: string | null
    state?: unknown
    /** Whether this job is a trial run (stores browsable results instead of ingesting). */
    readonly is_trial: boolean
    /** @nullable */
    readonly trial_record_limit: number | null
}

/**
 * One page of trial-run results, proxied from the trial output store.
 */
export interface TrialRecordsResponseApi {
    /** Trial records in source order: each has seq (global index), source (the original source event), outputs (the event(s) it would produce), and error (why it would be dropped, if it would be). */
    records: unknown[]
    /** Zero-based index of this page. */
    page: number
    /** Number of result pages written so far. */
    total_pages: number
    /** Number of source records processed so far. */
    total_records: number
    /** Running aggregates: output event name counts, error counts, dropped/skipped totals, timestamp range. */
    summary: unknown
}

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

export type ManagedMigrationsTrialRecordsRetrieveParams = {
    /**
     * Zero-based results page index (see total_pages in the response).
     */
    page?: number
}
