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

export interface OutcomeDefinitionApi {
    readonly id: string
    /**
     * Human-readable name of the outcome.
     * @maxLength 400
     */
    name: string
    /** What reaching this outcome means for the business. */
    description?: string
    /**
     * Name of the event the person must perform to reach the outcome.
     * @maxLength 400
     */
    target_event: string
    /**
     * Minimum number of times the person must perform the target event.
     * @minimum 1
     * @maximum 2147483647
     */
    threshold?: number
    /** Number of persons who have reached this outcome so far. */
    readonly reached_count: number
    /**
     * When the batch evaluator last ran for this outcome.
     * @nullable
     */
    readonly last_calculated_at: string | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi
}

export interface PaginatedOutcomeDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OutcomeDefinitionApi[]
}

export interface PatchedOutcomeDefinitionApi {
    readonly id?: string
    /**
     * Human-readable name of the outcome.
     * @maxLength 400
     */
    name?: string
    /** What reaching this outcome means for the business. */
    description?: string
    /**
     * Name of the event the person must perform to reach the outcome.
     * @maxLength 400
     */
    target_event?: string
    /**
     * Minimum number of times the person must perform the target event.
     * @minimum 1
     * @maximum 2147483647
     */
    threshold?: number
    /** Number of persons who have reached this outcome so far. */
    readonly reached_count?: number
    /**
     * When the batch evaluator last ran for this outcome.
     * @nullable
     */
    readonly last_calculated_at?: string | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly created_by?: UserBasicApi
}

export interface OutcomeLatchApi {
    readonly id: string
    /** UUID of the person who reached the outcome. */
    readonly person_id: string
    /** A distinct ID of the person, used for display and event emission. */
    readonly distinct_id: string
    /** Timestamp of the threshold-crossing event — a function of the event set alone. */
    readonly reached_at: string
    /** How many times the person had performed the target event when evaluated. */
    readonly event_count: number
    readonly created_at: string
}

export type OutcomesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
