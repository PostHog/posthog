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

/**
 * Return the targeting flag filters, excluding the base exclusion properties.
 * @nullable
 */
export type ProductTourApiTargetingFlagFilters = { [key: string]: unknown } | null | null

/**
 * Read-only serializer for ProductTour.
 */
export interface ProductTourApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    description?: string
    readonly internal_targeting_flag: MinimalFeatureFlagApi
    readonly linked_flag: MinimalFeatureFlagApi
    /**
     * Return the targeting flag filters, excluding the base exclusion properties.
     * @nullable
     */
    readonly targeting_flag_filters: ProductTourApiTargetingFlagFilters
    content?: unknown
    auto_launch?: boolean
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    archived?: boolean
}

export interface PaginatedProductTourListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ProductTourApi[]
}

/**
 * * `app` - app
 * `toolbar` - toolbar
 */
export type ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi =
    (typeof ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi)[keyof typeof ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi]

export const ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi = {
    app: 'app',
    toolbar: 'toolbar',
} as const

/**
 * Serializer for creating and updating ProductTour.
 */
export interface ProductTourSerializerCreateUpdateOnlyApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    description?: string
    readonly internal_targeting_flag: MinimalFeatureFlagApi
    readonly linked_flag: MinimalFeatureFlagApi
    /** @nullable */
    linked_flag_id?: number | null
    targeting_flag_filters?: unknown | null
    content?: unknown
    auto_launch?: boolean
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    archived?: boolean
    /** Where the tour was created/updated from

* `app` - app
* `toolbar` - toolbar */
    creation_context?: ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi
}

/**
 * Serializer for creating and updating ProductTour.
 */
export interface PatchedProductTourSerializerCreateUpdateOnlyApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    description?: string
    readonly internal_targeting_flag?: MinimalFeatureFlagApi
    readonly linked_flag?: MinimalFeatureFlagApi
    /** @nullable */
    linked_flag_id?: number | null
    targeting_flag_filters?: unknown | null
    content?: unknown
    auto_launch?: boolean
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    archived?: boolean
    /** Where the tour was created/updated from

* `app` - app
* `toolbar` - toolbar */
    creation_context?: ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi
}

export type ProductToursListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}
