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
 * Serializer for extracted tasks
 */
export interface TaskApi {
    title: string
    description?: string
    /** @nullable */
    assignee?: string | null
}

export interface PaginatedTaskListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskApi[]
}

/**
 * * `error_tracking` - Error Tracking
 * `eval_clusters` - Eval Clusters
 * `user_created` - User Created
 * `support_queue` - Support Queue
 * `session_summaries` - Session Summaries
 */
export type OriginProductEnumApi = (typeof OriginProductEnumApi)[keyof typeof OriginProductEnumApi]

export const OriginProductEnumApi = {
    error_tracking: 'error_tracking',
    eval_clusters: 'eval_clusters',
    user_created: 'user_created',
    support_queue: 'support_queue',
    session_summaries: 'session_summaries',
} as const

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

export interface PatchedTaskApi {
    readonly id?: string
    /** @nullable */
    readonly task_number?: number | null
    readonly slug?: string
    /** @maxLength 255 */
    title?: string
    description?: string
    origin_product?: OriginProductEnumApi
    /**
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * GitHub integration for this task
     * @nullable
     */
    github_integration?: number | null
    /** JSON schema for the task. This is used to validate the output of the task. */
    json_schema?: unknown | null
    readonly latest_run?: string
    readonly created_at?: string
    readonly updated_at?: string
    readonly created_by?: UserBasicApi
}

/**
 * * `not_started` - Not Started
 * `queued` - Queued
 * `in_progress` - In Progress
 * `completed` - Completed
 * `failed` - Failed
 * `cancelled` - Cancelled
 */
export type TaskRunDetailStatusEnumApi = (typeof TaskRunDetailStatusEnumApi)[keyof typeof TaskRunDetailStatusEnumApi]

export const TaskRunDetailStatusEnumApi = {
    not_started: 'not_started',
    queued: 'queued',
    in_progress: 'in_progress',
    completed: 'completed',
    failed: 'failed',
    cancelled: 'cancelled',
} as const

/**
 * * `local` - Local
 * `cloud` - Cloud
 */
export type EnvironmentEnumApi = (typeof EnvironmentEnumApi)[keyof typeof EnvironmentEnumApi]

export const EnvironmentEnumApi = {
    local: 'local',
    cloud: 'cloud',
} as const

export interface TaskRunArtifactResponseApi {
    /** Artifact file name */
    name: string
    /** Artifact classification (plan, context, etc.) */
    type: string
    /** Artifact size in bytes */
    size?: number
    /** Optional MIME type */
    content_type?: string
    /** S3 object key for the artifact */
    storage_path: string
    /** Timestamp when the artifact was uploaded */
    uploaded_at: string
}

export interface TaskRunDetailApi {
    readonly id: string
    readonly task: string
    /**
     * Current stage for this run (e.g., 'research', 'plan', 'build')
     * @maxLength 100
     * @nullable
     */
    stage?: string | null
    /**
     * Branch name for the run
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    status?: TaskRunDetailStatusEnumApi
    /** Execution environment

* `local` - Local
* `cloud` - Cloud */
    environment?: EnvironmentEnumApi
    /**
     * Presigned S3 URL for log access (valid for 1 hour).
     * @nullable
     */
    readonly log_url: string | null
    /**
     * Error message if execution failed
     * @nullable
     */
    error_message?: string | null
    /** Run output data (e.g., PR URL, commit SHA, etc.) */
    output?: unknown | null
    /** Run state data for resuming or tracking execution state */
    state?: unknown
    readonly artifacts: readonly TaskRunArtifactResponseApi[]
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    readonly completed_at: string | null
}

export interface PaginatedTaskRunDetailListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskRunDetailApi[]
}

/**
 * * `not_started` - not_started
 * `queued` - queued
 * `in_progress` - in_progress
 * `completed` - completed
 * `failed` - failed
 * `cancelled` - cancelled
 */
export type TaskRunUpdateStatusEnumApi = (typeof TaskRunUpdateStatusEnumApi)[keyof typeof TaskRunUpdateStatusEnumApi]

export const TaskRunUpdateStatusEnumApi = {
    not_started: 'not_started',
    queued: 'queued',
    in_progress: 'in_progress',
    completed: 'completed',
    failed: 'failed',
    cancelled: 'cancelled',
} as const

export interface PatchedTaskRunUpdateApi {
    /** Current execution status

* `not_started` - not_started
* `queued` - queued
* `in_progress` - in_progress
* `completed` - completed
* `failed` - failed
* `cancelled` - cancelled */
    status?: TaskRunUpdateStatusEnumApi
    /**
     * Git branch name to associate with the task
     * @nullable
     */
    branch?: string | null
    /**
     * Current stage of the run (e.g. research, plan, build)
     * @nullable
     */
    stage?: string | null
    /** Output from the run */
    output?: unknown | null
    /** State of the run */
    state?: unknown
    /**
     * Error message if execution failed
     * @nullable
     */
    error_message?: string | null
}

export interface ErrorResponseApi {
    /** Error message */
    error: string
}

export type TaskRunAppendLogRequestApiEntriesItem = { [key: string]: unknown }

export interface TaskRunAppendLogRequestApi {
    /** Array of log entry dictionaries to append */
    entries: TaskRunAppendLogRequestApiEntriesItem[]
}

/**
 * * `plan` - plan
 * `context` - context
 * `reference` - reference
 * `output` - output
 * `artifact` - artifact
 */
export type TaskRunArtifactUploadTypeEnumApi =
    (typeof TaskRunArtifactUploadTypeEnumApi)[keyof typeof TaskRunArtifactUploadTypeEnumApi]

export const TaskRunArtifactUploadTypeEnumApi = {
    plan: 'plan',
    context: 'context',
    reference: 'reference',
    output: 'output',
    artifact: 'artifact',
} as const

export interface TaskRunArtifactUploadApi {
    /**
     * File name to associate with the artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact

* `plan` - plan
* `context` - context
* `reference` - reference
* `output` - output
* `artifact` - artifact */
    type: TaskRunArtifactUploadTypeEnumApi
    /** Raw file contents (UTF-8 string or base64 data) */
    content: string
    /**
     * Optional MIME type for the artifact
     * @maxLength 255
     */
    content_type?: string
}

export interface TaskRunArtifactsUploadRequestApi {
    /** Array of artifacts to upload */
    artifacts: TaskRunArtifactUploadApi[]
}

export interface TaskRunArtifactsUploadResponseApi {
    /** Updated list of artifacts on the run */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskRunArtifactPresignRequestApi {
    /**
     * S3 storage path returned in the artifact manifest
     * @maxLength 500
     */
    storage_path: string
}

export interface TaskRunArtifactPresignResponseApi {
    /** Presigned URL for downloading the artifact */
    url: string
    /** URL expiry in seconds */
    expires_in: number
}

export type TasksListParams = {
    /**
     * Filter by creator user ID
     */
    created_by?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by repository organization
     * @minLength 1
     */
    organization?: string
    /**
     * Filter by origin product
     * @minLength 1
     */
    origin_product?: string
    /**
     * Filter by repository name (can include org/repo format)
     * @minLength 1
     */
    repository?: string
    /**
     * Filter by task run stage
     * @minLength 1
     */
    stage?: string
}

export type TasksRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
