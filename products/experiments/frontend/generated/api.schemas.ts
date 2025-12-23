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
 * * `web` - web
 * `product` - product
 */
export type ExperimentTypeEnumApi = (typeof ExperimentTypeEnumApi)[keyof typeof ExperimentTypeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ExperimentTypeEnumApi = {
    web: 'web',
    product: 'product',
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
 * * `won` - Won
 * `lost` - Lost
 * `inconclusive` - Inconclusive
 * `stopped_early` - Stopped Early
 * `invalid` - Invalid
 */
export type ConclusionEnumApi = (typeof ConclusionEnumApi)[keyof typeof ConclusionEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ConclusionEnumApi = {
    won: 'won',
    lost: 'lost',
    inconclusive: 'inconclusive',
    stopped_early: 'stopped_early',
    invalid: 'invalid',
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

export interface PaginatedExperimentHoldoutListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExperimentHoldoutApi[]
}

export interface ExperimentHoldoutApi {
    readonly id: number
    /** @maxLength 400 */
    name: string
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    filters?: unknown
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
}

export interface PatchedExperimentHoldoutApi {
    readonly id?: number
    /** @maxLength 400 */
    name?: string
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    filters?: unknown
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
}

export interface PaginatedExperimentListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExperimentApi[]
}

/**
 * @nullable
 */
export type ExperimentApiParameters = unknown | null

/**
 * @nullable
 */
export type ExperimentApiSecondaryMetrics = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ExperimentApiType = { ...ExperimentTypeEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type ExperimentApiType = (typeof ExperimentApiType)[keyof typeof ExperimentApiType] | null

/**
 * @nullable
 */
export type ExperimentApiExposureCriteria = unknown | null

/**
 * @nullable
 */
export type ExperimentApiMetrics = unknown | null

/**
 * @nullable
 */
export type ExperimentApiMetricsSecondary = unknown | null

/**
 * @nullable
 */
export type ExperimentApiStatsConfig = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ExperimentApiConclusion = { ...ConclusionEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type ExperimentApiConclusion = (typeof ExperimentApiConclusion)[keyof typeof ExperimentApiConclusion] | null

/**
 * @nullable
 */
export type ExperimentApiPrimaryMetricsOrderedUuids = unknown | null

/**
 * @nullable
 */
export type ExperimentApiSecondaryMetricsOrderedUuids = unknown | null

/**
 * Mixin for serializers to add user access control fields
 */
export interface ExperimentApi {
    readonly id: number
    /** @maxLength 400 */
    name: string
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    feature_flag_key: string
    readonly feature_flag: MinimalFeatureFlagApi
    readonly holdout: ExperimentHoldoutApi
    /** @nullable */
    holdout_id?: number | null
    /** @nullable */
    readonly exposure_cohort: number | null
    /** @nullable */
    parameters?: ExperimentApiParameters
    /** @nullable */
    secondary_metrics?: ExperimentApiSecondaryMetrics
    readonly saved_metrics: readonly ExperimentToSavedMetricApi[]
    /** @nullable */
    saved_metrics_ids?: unknown[] | null
    filters?: unknown
    archived?: boolean
    /** @nullable */
    deleted?: boolean | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    type?: ExperimentApiType
    /** @nullable */
    exposure_criteria?: ExperimentApiExposureCriteria
    /** @nullable */
    metrics?: ExperimentApiMetrics
    /** @nullable */
    metrics_secondary?: ExperimentApiMetricsSecondary
    /** @nullable */
    stats_config?: ExperimentApiStatsConfig
    _create_in_folder?: string
    /** @nullable */
    conclusion?: ExperimentApiConclusion
    /** @nullable */
    conclusion_comment?: string | null
    /** @nullable */
    primary_metrics_ordered_uuids?: ExperimentApiPrimaryMetricsOrderedUuids
    /** @nullable */
    secondary_metrics_ordered_uuids?: ExperimentApiSecondaryMetricsOrderedUuids
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

/**
 * @nullable
 */
export type PatchedExperimentApiParameters = unknown | null

/**
 * @nullable
 */
export type PatchedExperimentApiSecondaryMetrics = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PatchedExperimentApiType = { ...ExperimentTypeEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type PatchedExperimentApiType = (typeof PatchedExperimentApiType)[keyof typeof PatchedExperimentApiType] | null

/**
 * @nullable
 */
export type PatchedExperimentApiExposureCriteria = unknown | null

/**
 * @nullable
 */
export type PatchedExperimentApiMetrics = unknown | null

/**
 * @nullable
 */
export type PatchedExperimentApiMetricsSecondary = unknown | null

/**
 * @nullable
 */
export type PatchedExperimentApiStatsConfig = unknown | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PatchedExperimentApiConclusion = { ...ConclusionEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type PatchedExperimentApiConclusion =
    | (typeof PatchedExperimentApiConclusion)[keyof typeof PatchedExperimentApiConclusion]
    | null

/**
 * @nullable
 */
export type PatchedExperimentApiPrimaryMetricsOrderedUuids = unknown | null

/**
 * @nullable
 */
export type PatchedExperimentApiSecondaryMetricsOrderedUuids = unknown | null

/**
 * Mixin for serializers to add user access control fields
 */
export interface PatchedExperimentApi {
    readonly id?: number
    /** @maxLength 400 */
    name?: string
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    feature_flag_key?: string
    readonly feature_flag?: MinimalFeatureFlagApi
    readonly holdout?: ExperimentHoldoutApi
    /** @nullable */
    holdout_id?: number | null
    /** @nullable */
    readonly exposure_cohort?: number | null
    /** @nullable */
    parameters?: PatchedExperimentApiParameters
    /** @nullable */
    secondary_metrics?: PatchedExperimentApiSecondaryMetrics
    readonly saved_metrics?: readonly ExperimentToSavedMetricApi[]
    /** @nullable */
    saved_metrics_ids?: unknown[] | null
    filters?: unknown
    archived?: boolean
    /** @nullable */
    deleted?: boolean | null
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
    /** @nullable */
    type?: PatchedExperimentApiType
    /** @nullable */
    exposure_criteria?: PatchedExperimentApiExposureCriteria
    /** @nullable */
    metrics?: PatchedExperimentApiMetrics
    /** @nullable */
    metrics_secondary?: PatchedExperimentApiMetricsSecondary
    /** @nullable */
    stats_config?: PatchedExperimentApiStatsConfig
    _create_in_folder?: string
    /** @nullable */
    conclusion?: PatchedExperimentApiConclusion
    /** @nullable */
    conclusion_comment?: string | null
    /** @nullable */
    primary_metrics_ordered_uuids?: PatchedExperimentApiPrimaryMetricsOrderedUuids
    /** @nullable */
    secondary_metrics_ordered_uuids?: PatchedExperimentApiSecondaryMetricsOrderedUuids
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
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

export interface ExperimentToSavedMetricApi {
    readonly id: number
    experiment: number
    saved_metric: number
    metadata?: unknown
    readonly created_at: string
    readonly query: unknown
    readonly name: string
}

export type ExperimentHoldoutsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ExperimentsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
