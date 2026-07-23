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
 * * `marketing` - Marketing
 * * `transactional` - Transactional
 */
export type CategoryTypeEnumApi = (typeof CategoryTypeEnumApi)[keyof typeof CategoryTypeEnumApi]

export const CategoryTypeEnumApi = {
    Marketing: 'marketing',
    Transactional: 'transactional',
} as const

export interface MessageCategoryApi {
    readonly id: string
    /** @maxLength 64 */
    key: string
    /** @maxLength 128 */
    name: string
    description?: string
    public_description?: string
    category_type?: CategoryTypeEnumApi
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    readonly created_by: number | null
    deleted?: boolean
}

export interface PaginatedMessageCategoryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MessageCategoryApi[]
}

export interface PatchedMessageCategoryApi {
    readonly id?: string
    /** @maxLength 64 */
    key?: string
    /** @maxLength 128 */
    name?: string
    description?: string
    public_description?: string
    category_type?: CategoryTypeEnumApi
    readonly created_at?: string
    readonly updated_at?: string
    /** @nullable */
    readonly created_by?: number | null
    deleted?: boolean
}

export interface AddOptOutRequestApi {
    /**
     * The recipient identifier to opt out (e.g. email address).
     * @maxLength 512
     */
    identifier: string
    /** Optional message category key. If omitted, the recipient is opted out of all marketing messages. */
    category_key?: string
}

export interface MessagePreferencesApi {
    readonly id: string
    /** The recipient identifier (e.g. email address). */
    identifier: string
    /** When the preference was last updated. */
    updated_at: string
    /** Map of category ID to preference status. */
    preferences: unknown
}

export interface AddSuppressionRequestApi {
    /**
     * The email address to suppress. Will not receive any messages until removed.
     * @maxLength 512
     */
    identifier: string
}

/**
 * * `BOUNCE` - Bounce
 * * `MANUAL` - Manual
 */
export type MessageSuppressionSourceEnumApi =
    (typeof MessageSuppressionSourceEnumApi)[keyof typeof MessageSuppressionSourceEnumApi]

export const MessageSuppressionSourceEnumApi = {
    Bounce: 'BOUNCE',
    Manual: 'MANUAL',
} as const

export interface MessageSuppressionApi {
    /** Server-assigned UUID for this suppression entry. */
    readonly id: string
    /** Normalized recipient email address. Suppression is keyed on this value, per team. */
    readonly identifier: string
    /** How the entry landed on the list: `BOUNCE` for automatic (bounce-driven), `MANUAL` for user-added via the UI/API.
     *
     * * `BOUNCE` - Bounce
     * * `MANUAL` - Manual */
    readonly source: MessageSuppressionSourceEnumApi
    /**
     * Human-readable reason for the suppression (e.g. 'Auto-suppressed after 5 consecutive soft bounces').
     * @nullable
     */
    readonly reason: string | null
    /** Rolling count of consecutive soft bounces with no successful delivery in between. Reset to 0 on any successful delivery. Ignored for MANUAL entries. */
    readonly transient_bounce_count: number
    /**
     * Timestamp of the most recent bounce, if any.
     * @nullable
     */
    readonly last_bounce_at: string | null
    /**
     * SMTP diagnostic string from the most recent bounce (e.g. '550 5.1.1 user unknown'), kept for visibility.
     * @nullable
     */
    readonly last_bounce_diagnostic: string | null
    /** Whether the address is actively suppressed. A BOUNCE row can exist while still only counting bounces (suppressed=false) before it crosses the threshold. */
    readonly suppressed: boolean
    /**
     * Timestamp when the address was first suppressed.
     * @nullable
     */
    readonly suppressed_at: string | null
    /** When the row was first created (first bounce or manual add). */
    readonly created_at: string
    /** When the row was last touched by any write. */
    readonly updated_at: string
}

/**
 * OpenAPI shape for the paginated suppressions response. Declared so drf-spectacular emits
 * the {count, next, previous, results} envelope on the generated client, rather than a bare
 * array — which the frontend actually receives at runtime.
 */
export interface PaginatedMessageSuppressionApi {
    /** Total number of suppressed recipients for the team. */
    count: number
    /**
     * URL for the next page, or null on the last page.
     * @nullable
     */
    next: string | null
    /**
     * URL for the previous page, or null on the first page.
     * @nullable
     */
    previous: string | null
    results: MessageSuppressionApi[]
}

export type MessagingCategoriesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type MessagingSuppressionsSuppressionsRetrieveParams = {
    page?: number
    page_size?: number
}
