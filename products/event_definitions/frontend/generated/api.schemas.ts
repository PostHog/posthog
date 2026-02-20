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
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
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

/**
 * * `allow` - Allow
 * `reject` - Reject
 */
export type EnforcementModeEnumApi = (typeof EnforcementModeEnumApi)[keyof typeof EnforcementModeEnumApi]

export const EnforcementModeEnumApi = {
    Allow: 'allow',
    Reject: 'reject',
} as const

/**
 * Serializer mixin that handles tags for objects.
 */
export interface EnterpriseEventDefinitionApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    /** @nullable */
    owner?: number | null
    /** @nullable */
    description?: string | null
    tags?: unknown[]
    /** @nullable */
    readonly created_at: string | null
    readonly updated_at: string
    readonly updated_by: UserBasicApi
    /** @nullable */
    readonly last_seen_at: string | null
    readonly last_updated_at: string
    verified?: boolean
    /** @nullable */
    readonly verified_at: string | null
    readonly verified_by: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
    enforcement_mode?: EnforcementModeEnumApi
    readonly is_action: boolean
    readonly action_id: number
    readonly is_calculating: boolean
    readonly last_calculated_at: string
    readonly created_by: UserBasicApi
    post_to_slack?: boolean
    default_columns?: string[]
    readonly media_preview_urls: readonly string[]
}

export interface PaginatedEnterpriseEventDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EnterpriseEventDefinitionApi[]
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface PatchedEnterpriseEventDefinitionApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    /** @nullable */
    owner?: number | null
    /** @nullable */
    description?: string | null
    tags?: unknown[]
    /** @nullable */
    readonly created_at?: string | null
    readonly updated_at?: string
    readonly updated_by?: UserBasicApi
    /** @nullable */
    readonly last_seen_at?: string | null
    readonly last_updated_at?: string
    verified?: boolean
    /** @nullable */
    readonly verified_at?: string | null
    readonly verified_by?: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
    enforcement_mode?: EnforcementModeEnumApi
    readonly is_action?: boolean
    readonly action_id?: number
    readonly is_calculating?: boolean
    readonly last_calculated_at?: string
    readonly created_by?: UserBasicApi
    post_to_slack?: boolean
    default_columns?: string[]
    readonly media_preview_urls?: readonly string[]
}

export type EventDefinitionApiProperties = { [key: string]: unknown }

export interface EventDefinitionApi {
    elements: unknown[]
    event: string
    properties: EventDefinitionApiProperties
}

export type EventDefinitionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EventDefinitionsByNameRetrieveParams = {
    /**
     * The exact event name to look up
     */
    name: string
}
