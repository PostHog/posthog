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

export interface DatasetItemApi {
    readonly id: string
    dataset: string
    input?: unknown | null
    output?: unknown | null
    metadata?: unknown | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_trace_id?: string | null
    /** @nullable */
    ref_timestamp?: string | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_source_id?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedDatasetItemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DatasetItemApi[]
}

export interface PatchedDatasetItemApi {
    readonly id?: string
    dataset?: string
    input?: unknown | null
    output?: unknown | null
    metadata?: unknown | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_trace_id?: string | null
    /** @nullable */
    ref_timestamp?: string | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_source_id?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly created_by?: UserBasicApi
    readonly team?: number
}

export interface DatasetApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    /** @nullable */
    description?: string | null
    metadata?: unknown | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedDatasetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DatasetApi[]
}

export interface PatchedDatasetApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    /** @nullable */
    description?: string | null
    metadata?: unknown | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_by?: UserBasicApi
    readonly team?: number
}

export type EnvironmentsDatasetItemsListParams = {
    /**
     * Filter by dataset ID
     */
    dataset?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsDatasetsListParams = {
    /**
     * Multiple values may be separated by commas.
     */
    id__in?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Ordering

* `created_at` - Created At
* `-created_at` - Created At (descending)
* `updated_at` - Updated At
* `-updated_at` - Updated At (descending)
 */
    order_by?: EnvironmentsDatasetsListOrderByItem[]
    /**
     * Search in name, description, or metadata
     */
    search?: string
}

export type EnvironmentsDatasetsListOrderByItem =
    (typeof EnvironmentsDatasetsListOrderByItem)[keyof typeof EnvironmentsDatasetsListOrderByItem]

export const EnvironmentsDatasetsListOrderByItem = {
    '-created_at': '-created_at',
    '-updated_at': '-updated_at',
    created_at: 'created_at',
    updated_at: 'updated_at',
} as const

export type DatasetItemsListParams = {
    /**
     * Filter by dataset ID
     */
    dataset?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DatasetsListParams = {
    /**
     * Multiple values may be separated by commas.
     */
    id__in?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Ordering

* `created_at` - Created At
* `-created_at` - Created At (descending)
* `updated_at` - Updated At
* `-updated_at` - Updated At (descending)
 */
    order_by?: DatasetsListOrderByItem[]
    /**
     * Search in name, description, or metadata
     */
    search?: string
}

export type DatasetsListOrderByItem = (typeof DatasetsListOrderByItem)[keyof typeof DatasetsListOrderByItem]

export const DatasetsListOrderByItem = {
    '-created_at': '-created_at',
    '-updated_at': '-updated_at',
    created_at: 'created_at',
    updated_at: 'updated_at',
} as const
