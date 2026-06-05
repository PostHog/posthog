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
export type BatchImportApiCreatedBy = { [key: string]: unknown } | null

/**
 * * `completed` - Completed
 * `failed` - Failed
 * `paused` - Paused
 * `running` - Running
 */
export type BatchImportStatusEnumApi = (typeof BatchImportStatusEnumApi)[keyof typeof BatchImportStatusEnumApi]

export const BatchImportStatusEnumApi = {
    Completed: 'completed',
    Failed: 'failed',
    Paused: 'paused',
    Running: 'running',
} as const

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
