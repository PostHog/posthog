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
 * `failed` - Failed
 * `paused` - Paused
 * `running` - Running
 */
export type BatchImportStatusEnumApi = (typeof BatchImportStatusEnumApi)[keyof typeof BatchImportStatusEnumApi]

export const BatchImportStatusEnumApi = {
    completed: 'completed',
    failed: 'failed',
    paused: 'paused',
    running: 'running',
} as const

/**
 * Serializer for BatchImport model
 */
export interface BatchImportApi {
    readonly id: string
    readonly team_id: number
    readonly created_at: string
    readonly updated_at: string
    readonly state: unknown | null
    readonly created_by: string
    status?: BatchImportStatusEnumApi
    /** @nullable */
    readonly display_status_message: string | null
    import_config: unknown
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
 * Serializer for BatchImport model
 */
export interface PatchedBatchImportApi {
    readonly id?: string
    readonly team_id?: number
    readonly created_at?: string
    readonly updated_at?: string
    readonly state?: unknown | null
    readonly created_by?: string
    status?: BatchImportStatusEnumApi
    /** @nullable */
    readonly display_status_message?: string | null
    import_config?: unknown
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
     * `failed` - Failed
     * `paused` - Paused
     * `running` - Running
     */
    status?: ManagedMigrationsListStatus
}

export type ManagedMigrationsListStatus = (typeof ManagedMigrationsListStatus)[keyof typeof ManagedMigrationsListStatus]

export const ManagedMigrationsListStatus = {
    completed: 'completed',
    failed: 'failed',
    paused: 'paused',
    running: 'running',
} as const
