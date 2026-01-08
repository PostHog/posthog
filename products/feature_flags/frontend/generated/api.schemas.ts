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
 * * `feature_flags` - feature_flags
 * `experiments` - experiments
 * `surveys` - surveys
 * `early_access_features` - early_access_features
 * `web_experiments` - web_experiments
 * `product_tours` - product_tours
 */
export type CreationContextEnumApi = (typeof CreationContextEnumApi)[keyof typeof CreationContextEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CreationContextEnumApi = {
    feature_flags: 'feature_flags',
    experiments: 'experiments',
    surveys: 'surveys',
    early_access_features: 'early_access_features',
    web_experiments: 'web_experiments',
    product_tours: 'product_tours',
} as const

/**
 * * `server` - Server
 * `client` - Client
 * `all` - All
 */
export type EvaluationRuntimeEnumApi = (typeof EvaluationRuntimeEnumApi)[keyof typeof EvaluationRuntimeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EvaluationRuntimeEnumApi = {
    server: 'server',
    client: 'client',
    all: 'all',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const NullEnumApi = {} as const

/**
 * * `distinct_id` - User ID (default)
 * `device_id` - Device ID
 */
export type BucketingIdentifierEnumApi = (typeof BucketingIdentifierEnumApi)[keyof typeof BucketingIdentifierEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BucketingIdentifierEnumApi = {
    distinct_id: 'distinct_id',
    device_id: 'device_id',
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

export interface PaginatedFeatureFlagListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: FeatureFlagApi[]
}

export type FeatureFlagApiFilters = { [key: string]: unknown }

export type FeatureFlagApiSurveys = { [key: string]: unknown }

export type FeatureFlagApiFeatures = { [key: string]: unknown }

/**
 * @nullable
 */
export type FeatureFlagApiRollbackConditions = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FeatureFlagApiEvaluationRuntime = { ...EvaluationRuntimeEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All
 * @nullable
 */
export type FeatureFlagApiEvaluationRuntime =
    | (typeof FeatureFlagApiEvaluationRuntime)[keyof typeof FeatureFlagApiEvaluationRuntime]
    | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FeatureFlagApiBucketingIdentifier = {
    ...BucketingIdentifierEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID
 * @nullable
 */
export type FeatureFlagApiBucketingIdentifier =
    | (typeof FeatureFlagApiBucketingIdentifier)[keyof typeof FeatureFlagApiBucketingIdentifier]
    | null

/**
 * Serializer mixin that resolves appropriate response for tags depending on license.
 */
export interface FeatureFlagApi {
    readonly id: number
    /** contains the description for the flag (field name `name` is kept for backwards-compatibility) */
    name?: string
    /** @maxLength 400 */
    key: string
    filters?: FeatureFlagApiFilters
    deleted?: boolean
    active?: boolean
    readonly created_by: UserBasicApi
    created_at?: string
    /** @nullable */
    readonly updated_at: string | null
    version?: number
    readonly last_modified_by: UserBasicApi
    readonly is_simple_flag: boolean
    /** @nullable */
    readonly rollout_percentage: number | null
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    readonly experiment_set: string
    readonly surveys: FeatureFlagApiSurveys
    readonly features: FeatureFlagApiFeatures
    /** @nullable */
    rollback_conditions?: FeatureFlagApiRollbackConditions
    /** @nullable */
    performed_rollback?: boolean | null
    readonly can_edit: boolean
    tags?: unknown[]
    evaluation_tags?: unknown[]
    readonly usage_dashboard: number
    analytics_dashboards?: number[]
    /** @nullable */
    has_enriched_analytics?: boolean | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    /** Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.

* `feature_flags` - feature_flags
* `experiments` - experiments
* `surveys` - surveys
* `early_access_features` - early_access_features
* `web_experiments` - web_experiments
* `product_tours` - product_tours */
    creation_context?: CreationContextEnumApi
    /** @nullable */
    is_remote_configuration?: boolean | null
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    readonly status: string
    /**
   * Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All
   * @nullable
   */
    evaluation_runtime?: FeatureFlagApiEvaluationRuntime
    /**
   * Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID
   * @nullable
   */
    bucketing_identifier?: FeatureFlagApiBucketingIdentifier
    /**
     * Last time this feature flag was called (from $feature_flag_called events)
     * @nullable
     */
    last_called_at?: string | null
    _create_in_folder?: string
    _should_create_usage_dashboard?: boolean
}

export type PatchedFeatureFlagApiFilters = { [key: string]: unknown }

export type PatchedFeatureFlagApiSurveys = { [key: string]: unknown }

export type PatchedFeatureFlagApiFeatures = { [key: string]: unknown }

/**
 * @nullable
 */
export type PatchedFeatureFlagApiRollbackConditions = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PatchedFeatureFlagApiEvaluationRuntime = {
    ...EvaluationRuntimeEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All
 * @nullable
 */
export type PatchedFeatureFlagApiEvaluationRuntime =
    | (typeof PatchedFeatureFlagApiEvaluationRuntime)[keyof typeof PatchedFeatureFlagApiEvaluationRuntime]
    | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PatchedFeatureFlagApiBucketingIdentifier = {
    ...BucketingIdentifierEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID
 * @nullable
 */
export type PatchedFeatureFlagApiBucketingIdentifier =
    | (typeof PatchedFeatureFlagApiBucketingIdentifier)[keyof typeof PatchedFeatureFlagApiBucketingIdentifier]
    | null

/**
 * Serializer mixin that resolves appropriate response for tags depending on license.
 */
export interface PatchedFeatureFlagApi {
    readonly id?: number
    /** contains the description for the flag (field name `name` is kept for backwards-compatibility) */
    name?: string
    /** @maxLength 400 */
    key?: string
    filters?: PatchedFeatureFlagApiFilters
    deleted?: boolean
    active?: boolean
    readonly created_by?: UserBasicApi
    created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    version?: number
    readonly last_modified_by?: UserBasicApi
    readonly is_simple_flag?: boolean
    /** @nullable */
    readonly rollout_percentage?: number | null
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    readonly experiment_set?: string
    readonly surveys?: PatchedFeatureFlagApiSurveys
    readonly features?: PatchedFeatureFlagApiFeatures
    /** @nullable */
    rollback_conditions?: PatchedFeatureFlagApiRollbackConditions
    /** @nullable */
    performed_rollback?: boolean | null
    readonly can_edit?: boolean
    tags?: unknown[]
    evaluation_tags?: unknown[]
    readonly usage_dashboard?: number
    analytics_dashboards?: number[]
    /** @nullable */
    has_enriched_analytics?: boolean | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
    /** Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.

* `feature_flags` - feature_flags
* `experiments` - experiments
* `surveys` - surveys
* `early_access_features` - early_access_features
* `web_experiments` - web_experiments
* `product_tours` - product_tours */
    creation_context?: CreationContextEnumApi
    /** @nullable */
    is_remote_configuration?: boolean | null
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    readonly status?: string
    /**
   * Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All
   * @nullable
   */
    evaluation_runtime?: PatchedFeatureFlagApiEvaluationRuntime
    /**
   * Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID
   * @nullable
   */
    bucketing_identifier?: PatchedFeatureFlagApiBucketingIdentifier
    /**
     * Last time this feature flag was called (from $feature_flag_called events)
     * @nullable
     */
    last_called_at?: string | null
    _create_in_folder?: string
    _should_create_usage_dashboard?: boolean
}

/**
 * Response shape for paginated activity log endpoints.
 */
export interface ActivityLogPaginatedResponseApi {
    results: ActivityLogEntryApi[]
    /** @nullable */
    next: string | null
    /** @nullable */
    previous: string | null
    total_count: number
}

export type LocalEvaluationResponseApiGroupTypeMapping = { [key: string]: string }

/**
 * Cohort definitions keyed by cohort ID. Each value is a property group structure with 'type' (OR/AND) and 'values' (array of property groups or property filters).
 */
export type LocalEvaluationResponseApiCohorts = { [key: string]: unknown }

export interface LocalEvaluationResponseApi {
    flags: MinimalFeatureFlagApi[]
    group_type_mapping: LocalEvaluationResponseApiGroupTypeMapping
    /** Cohort definitions keyed by cohort ID. Each value is a property group structure with 'type' (OR/AND) and 'values' (array of property groups or property filters). */
    cohorts: LocalEvaluationResponseApiCohorts
}

export interface MyFlagsResponseApi {
    feature_flag: MinimalFeatureFlagApi
    value: unknown
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

export interface ActivityLogEntryApi {
    readonly user: string
    readonly activity: string
    readonly scope: string
    readonly item_id: string
    detail?: DetailApi
    readonly created_at: string
}

export type MinimalFeatureFlagApiFilters = { [key: string]: unknown }

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MinimalFeatureFlagApiEvaluationRuntime = {
    ...EvaluationRuntimeEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All
 * @nullable
 */
export type MinimalFeatureFlagApiEvaluationRuntime =
    | (typeof MinimalFeatureFlagApiEvaluationRuntime)[keyof typeof MinimalFeatureFlagApiEvaluationRuntime]
    | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MinimalFeatureFlagApiBucketingIdentifier = {
    ...BucketingIdentifierEnumApi,
    ...BlankEnumApi,
    ...NullEnumApi,
} as const
/**
 * Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID
 * @nullable
 */
export type MinimalFeatureFlagApiBucketingIdentifier =
    | (typeof MinimalFeatureFlagApiBucketingIdentifier)[keyof typeof MinimalFeatureFlagApiBucketingIdentifier]
    | null

export interface MinimalFeatureFlagApi {
    readonly id: number
    readonly team_id: number
    name?: string
    /** @maxLength 400 */
    key: string
    filters?: MinimalFeatureFlagApiFilters
    deleted?: boolean
    active?: boolean
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    version?: number | null
    /**
   * Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All
   * @nullable
   */
    evaluation_runtime?: MinimalFeatureFlagApiEvaluationRuntime
    /**
   * Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID
   * @nullable
   */
    bucketing_identifier?: MinimalFeatureFlagApiBucketingIdentifier
    readonly evaluation_tags: readonly string[]
}

export interface DetailApi {
    readonly id: string
    changes?: ChangeApi[]
    merge?: MergeApi
    trigger?: TriggerApi
    readonly name: string
    readonly short_id: string
    readonly type: string
}

export interface ChangeApi {
    readonly type: string
    readonly action: string
    readonly field: string
    readonly before: unknown
    readonly after: unknown
}

export interface MergeApi {
    readonly type: string
    readonly source: unknown
    readonly target: unknown
}

export interface TriggerApi {
    readonly job_type: string
    readonly job_id: string
    readonly payload: unknown
}

export type FeatureFlagsListParams = {
    active?: FeatureFlagsListActive
    /**
     * The User ID which initially created the feature flag.
     */
    created_by_id?: string
    /**
     * Filter feature flags by their evaluation runtime.
     */
    evaluation_runtime?: FeatureFlagsListEvaluationRuntime
    /**
     * JSON-encoded list of feature flag keys to exclude from the results.
     */
    excluded_properties?: string
    /**
     * Filter feature flags by presence of evaluation environment tags. 'true' returns only flags with at least one evaluation tag, 'false' returns only flags without evaluation tags.
     */
    has_evaluation_tags?: FeatureFlagsListHasEvaluationTags
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Search by feature flag key or name. Case insensitive.
     */
    search?: string
    /**
     * JSON-encoded list of tag names to filter feature flags by.
     */
    tags?: string
    type?: FeatureFlagsListType
}

export type FeatureFlagsListActive = (typeof FeatureFlagsListActive)[keyof typeof FeatureFlagsListActive]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FeatureFlagsListActive = {
    STALE: 'STALE',
    false: 'false',
    true: 'true',
} as const

export type FeatureFlagsListEvaluationRuntime =
    (typeof FeatureFlagsListEvaluationRuntime)[keyof typeof FeatureFlagsListEvaluationRuntime]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FeatureFlagsListEvaluationRuntime = {
    both: 'both',
    client: 'client',
    server: 'server',
} as const

export type FeatureFlagsListHasEvaluationTags =
    (typeof FeatureFlagsListHasEvaluationTags)[keyof typeof FeatureFlagsListHasEvaluationTags]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FeatureFlagsListHasEvaluationTags = {
    false: 'false',
    true: 'true',
} as const

export type FeatureFlagsListType = (typeof FeatureFlagsListType)[keyof typeof FeatureFlagsListType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FeatureFlagsListType = {
    boolean: 'boolean',
    experiment: 'experiment',
    multivariant: 'multivariant',
} as const

export type FeatureFlagsActivityRetrieve2Params = {
    /**
     * Number of items per page
     * @minimum 1
     */
    limit?: number
    /**
     * Page number
     * @minimum 1
     */
    page?: number
}

export type FeatureFlagsActivityRetrieveParams = {
    /**
     * Number of items per page
     * @minimum 1
     */
    limit?: number
    /**
     * Page number
     * @minimum 1
     */
    page?: number
}

export type FeatureFlagsEvaluationReasonsRetrieveParams = {
    /**
     * User distinct ID
     * @minLength 1
     */
    distinct_id: string
    /**
     * Groups for feature flag evaluation (JSON object string)
     */
    groups?: string
}

export type FeatureFlagsLocalEvaluationRetrieveParams = {
    /**
     * Include cohorts in response
     * @nullable
     */
    send_cohorts?: boolean | null
}

/**
 * Unspecified response body
 */
export type FeatureFlagsLocalEvaluationRetrieve402 = { [key: string]: unknown }

/**
 * Unspecified response body
 */
export type FeatureFlagsLocalEvaluationRetrieve500 = { [key: string]: unknown }

export type FeatureFlagsMyFlagsRetrieveParams = {
    /**
     * Groups for feature flag evaluation (JSON object string)
     */
    groups?: string
}
