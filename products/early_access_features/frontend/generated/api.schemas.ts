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
 * * `server` - Server
 * `client` - Client
 * `all` - All
 */
export type EvaluationRuntimeEnumApi = (typeof EvaluationRuntimeEnumApi)[keyof typeof EvaluationRuntimeEnumApi]

export const EvaluationRuntimeEnumApi = {
    server: 'server',
    client: 'client',
    all: 'all',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * * `distinct_id` - User ID (default)
 * `device_id` - Device ID
 */
export type BucketingIdentifierEnumApi = (typeof BucketingIdentifierEnumApi)[keyof typeof BucketingIdentifierEnumApi]

export const BucketingIdentifierEnumApi = {
    distinct_id: 'distinct_id',
    device_id: 'device_id',
} as const

export type MinimalFeatureFlagApiFilters = { [key: string]: unknown }

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
    /** Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | NullEnumApi | null
    /** Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | NullEnumApi | null
    readonly evaluation_tags: readonly string[]
}

/**
 * * `draft` - draft
 * `concept` - concept
 * `alpha` - alpha
 * `beta` - beta
 * `general-availability` - general availability
 * `archived` - archived
 */
export type StageEnumApi = (typeof StageEnumApi)[keyof typeof StageEnumApi]

export const StageEnumApi = {
    draft: 'draft',
    concept: 'concept',
    alpha: 'alpha',
    beta: 'beta',
    'general-availability': 'general-availability',
    archived: 'archived',
} as const

export interface EarlyAccessFeatureApi {
    readonly id: string
    readonly feature_flag: MinimalFeatureFlagApi
    /** @maxLength 200 */
    name: string
    description?: string
    stage: StageEnumApi
    /** @maxLength 800 */
    documentation_url?: string
    readonly payload: string
    readonly created_at: string
}

export interface PaginatedEarlyAccessFeatureListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EarlyAccessFeatureApi[]
}

export interface EarlyAccessFeatureSerializerCreateOnlyApi {
    readonly id: string
    /** @maxLength 200 */
    name: string
    description?: string
    stage: StageEnumApi
    /** @maxLength 800 */
    documentation_url?: string
    payload?: unknown
    readonly created_at: string
    feature_flag_id?: number
    readonly feature_flag: MinimalFeatureFlagApi
    _create_in_folder?: string
}

export interface PatchedEarlyAccessFeatureApi {
    readonly id?: string
    readonly feature_flag?: MinimalFeatureFlagApi
    /** @maxLength 200 */
    name?: string
    description?: string
    stage?: StageEnumApi
    /** @maxLength 800 */
    documentation_url?: string
    readonly payload?: string
    readonly created_at?: string
}

export type EarlyAccessFeatureListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
