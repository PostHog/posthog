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
 * * `count` - count
 * * `sum` - sum
 * * `distinct` - distinct
 */
export type OutcomeAggregationEnumApi = (typeof OutcomeAggregationEnumApi)[keyof typeof OutcomeAggregationEnumApi]

export const OutcomeAggregationEnumApi = {
    Count: 'count',
    Sum: 'sum',
    Distinct: 'distinct',
} as const

/**
 * A standard PostHog property filter (event property, person property, cohort, HogQL, ...), in the same shape the insights API accepts.
 */
export type OutcomeAtomApiPropertiesItem = { [key: string]: unknown }

export interface OutcomeAtomApi {
    /**
     * Name of the event this condition aggregates.
     * @maxLength 400
     */
    event: string
    /** Property filters an event must match to count toward this condition. */
    properties?: OutcomeAtomApiPropertiesItem[]
    /** Monotone aggregation over matching events: count of events, sum of a numeric property, or number of distinct values of a property.
     *
     * * `count` - count
     * * `sum` - sum
     * * `distinct` - distinct */
    aggregation?: OutcomeAggregationEnumApi
    /**
     * Event property to sum or count distinct values of; required for sum and distinct, must be empty for count.
     * @maxLength 400
     * @nullable
     */
    aggregation_property?: string | null
    /** The condition is satisfied once the aggregation reaches at least this value. Must be a whole number of at least 1 for count and distinct, greater than 0 for sum. */
    threshold?: number
}

export interface OutcomePathApi {
    /** Conditions combined within this path; all must be met unless min_matches is set. */
    atoms: OutcomeAtomApi[]
    /**
     * Satisfy the path when at least this many of its conditions are met (M-of-N). Leave empty to require all of them.
     * @minimum 1
     * @nullable
     */
    min_matches?: number | null
}

export interface OutcomeCriteriaApi {
    /** Paths OR'd together: a person reaches the outcome by completing any one path. */
    paths: OutcomePathApi[]
}

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
    /** Monotone criteria: paths OR'd together, conditions AND'd within a path (optionally M-of-N). */
    criteria: OutcomeCriteriaApi
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
    /** Monotone criteria: paths OR'd together, conditions AND'd within a path (optionally M-of-N). */
    criteria?: OutcomeCriteriaApi
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

/**
 * Aggregate values only: the winning path index and, per condition, the attained value against its threshold at latch time.
 */
export type OutcomeLatchApiEvidence = { [key: string]: unknown }

export interface OutcomeLatchApi {
    readonly id: string
    /** UUID of the person who reached the outcome. */
    readonly person_id: string
    /** A distinct ID of the person, used for display and event emission. */
    readonly distinct_id: string
    /** Timestamp of the threshold-crossing event — a function of the event set alone. */
    readonly reached_at: string
    /** Aggregate values only: the winning path index and, per condition, the attained value against its threshold at latch time. */
    readonly evidence: OutcomeLatchApiEvidence
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
