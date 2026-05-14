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

export interface UserInterviewTopicApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    /**
     * Optional cohort ID identifying who to target. Not enforced as a foreign key.
     * @nullable
     */
    interviewee_cohort?: number | null
    /** Email addresses of people to interview. May be combined with interviewee_cohort and interviewee_distinct_ids. */
    interviewee_emails?: string[]
    /** PostHog distinct IDs of people to interview. May be combined with interviewee_cohort and interviewee_emails. */
    interviewee_distinct_ids?: string[]
    /** The product, feature, or idea you want to ask interviewees about. */
    topic: string
    /** Optional additional system prompt for the voice agent — extra background, tone, or constraints. */
    agent_context?: string
    /** Ordered list of questions the voice agent should work through during the interview. */
    questions?: string[]
}

export interface PaginatedUserInterviewTopicListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserInterviewTopicApi[]
}

export interface PatchedUserInterviewTopicApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /**
     * Optional cohort ID identifying who to target. Not enforced as a foreign key.
     * @nullable
     */
    interviewee_cohort?: number | null
    /** Email addresses of people to interview. May be combined with interviewee_cohort and interviewee_distinct_ids. */
    interviewee_emails?: string[]
    /** PostHog distinct IDs of people to interview. May be combined with interviewee_cohort and interviewee_emails. */
    interviewee_distinct_ids?: string[]
    /** The product, feature, or idea you want to ask interviewees about. */
    topic?: string
    /** Optional additional system prompt for the voice agent — extra background, tone, or constraints. */
    agent_context?: string
    /** Ordered list of questions the voice agent should work through during the interview. */
    questions?: string[]
}

export interface IntervieweeContextApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    /**
     * Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids.
     * @maxLength 400
     */
    interviewee_identifier: string
    /**
     * Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'.
     * @maxLength 10000
     */
    agent_context: string
}

export interface PaginatedIntervieweeContextListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: IntervieweeContextApi[]
}

export interface PatchedIntervieweeContextApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /**
     * Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids.
     * @maxLength 400
     */
    interviewee_identifier?: string
    /**
     * Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'.
     * @maxLength 10000
     */
    agent_context?: string
}

export interface UserInterviewApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    interviewee_emails?: string[]
    readonly transcript: string
    summary?: string
    audio: string
}

export interface PaginatedUserInterviewListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserInterviewApi[]
}

export interface PatchedUserInterviewApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    interviewee_emails?: string[]
    readonly transcript?: string
    summary?: string
    audio?: string
}

export type UserInterviewTopicsListParams = {
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

export type UserInterviewTopicsIntervieweesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UserInterviewsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
