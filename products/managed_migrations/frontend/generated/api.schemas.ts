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
 * Values a customer needs to configure cross-account IAM role access for S3 imports
 */
export interface BatchImportAWSIAMSetupApi {
    /** Whether IAM role authentication is available on this PostHog deployment. */
    available: boolean
    /** External ID to pin in the role trust policy's sts:ExternalId condition. Stable per project. */
    external_id: string
    /** ARN of PostHog's import role - the principal your role must trust. */
    posthog_role_arn: string
    /** Ready-to-paste IAM trust policy JSON for the role in your AWS account. */
    trust_policy: string
    /** IAM permission policy JSON template; replace YOUR_BUCKET and YOUR_PREFIX with your values. */
    permission_policy_template: string
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
