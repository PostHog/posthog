/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface SocialReferralShopifyDiscountCodeRecordApi {
    /** Discount code string as created in Shopify Admin. */
    code: string
    /** ISO 8601 datetime when the code was created. */
    issued_at: string
    /** Shopify price rule id this code was created under. */
    price_rule_id: string
}

export interface SocialReferralRefereeInviteApi {
    /** UUID of the organization that signed up via this referral link. */
    organization_id: string
    /** Current display name of the invited organization. */
    organization_name: string
    /** Whether this organization has sent its first ingested event. */
    first_event_sent: boolean
    /**
     * ISO 8601 datetime when this organization was first attributed at signup, if recorded.
     * @nullable
     */
    signed_up_at?: string | null
    /**
     * Primary key of the user who signed up the invited organization; null if unknown or cleared.
     * @nullable
     */
    signed_up_user_id?: number | null
    /**
     * Resolved full name or email of signed_up_user_id when that user still exists; null if missing.
     * @nullable
     */
    signed_up_user_display_name?: string | null
    /** Shopify discount codes issued for this invited organization (append-only; multiple allowed). */
    readonly shopify_discount_codes: readonly SocialReferralShopifyDiscountCodeRecordApi[]
}

/**
 * Map of invited organization UUID (string) to referral progress (`first_event_sent`, `signed_up_at`, `signed_up_user_id`, `shopify_discount_codes`, etc.).
 */
export type SocialReferralApiRefereeState = { [key: string]: unknown }

export interface SocialReferralApi {
    readonly id: string
    readonly organization: string
    readonly user: number
    /** Map of invited organization UUID (string) to referral progress (`first_event_sent`, `signed_up_at`, `signed_up_user_id`, `shopify_discount_codes`, etc.). */
    referee_state?: SocialReferralApiRefereeState
    /** Invited organizations from referee_state with organization and signup-user display names resolved. */
    readonly referee_invites: readonly SocialReferralRefereeInviteApi[]
    readonly created_at: string
}

export interface PaginatedSocialReferralListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SocialReferralApi[]
}

export type SocialReferralsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
