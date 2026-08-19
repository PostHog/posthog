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
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
 * * `other` - Other
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
    Student: 'student',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface LinkApi {
    readonly id: string
    /** @maxLength 2048 */
    redirect_url: string
    /**
     * Domain where the short link is hosted, e.g. hog.gg
     * @maxLength 255
     */
    short_link_domain: string
    short_code: string
    /** @nullable */
    description?: string | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi
    _create_in_folder?: string
}

export interface PaginatedLinkListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LinkApi[]
}

export interface PatchedLinkApi {
    readonly id?: string
    /** @maxLength 2048 */
    redirect_url?: string
    /**
     * Domain where the short link is hosted, e.g. hog.gg
     * @maxLength 255
     */
    short_link_domain?: string
    short_code?: string
    /** @nullable */
    description?: string | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly created_by?: UserBasicApi
    _create_in_folder?: string
}

export type LinksListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
