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
 * * `error_tracking` - Error Tracking
 * `eval_clusters` - Eval Clusters
 * `user_created` - User Created
 * `support_queue` - Support Queue
 * `session_summaries` - Session Summaries
 */
export type OriginProductEnumApi = (typeof OriginProductEnumApi)[keyof typeof OriginProductEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const NullEnumApi = {} as const

export interface PaginatedTaskListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskApi[]
}

/**
 * Serializer for extracted tasks
 */
export interface TaskApi {
    title: string
    description?: string
    /** @nullable */
    assignee?: string | null
}

/**
 * JSON schema for the task. This is used to validate the output of the task.
 * @nullable
 */
export type PatchedTaskApiJsonSchema = unknown | null

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
    /**
     * JSON schema for the task. This is used to validate the output of the task.
     * @nullable
     */
    json_schema?: PatchedTaskApiJsonSchema
    readonly latest_run?: string
    readonly created_at?: string
    readonly updated_at?: string
    readonly created_by?: UserBasicApi
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

export type TasksListParams = {
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
