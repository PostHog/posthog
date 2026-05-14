/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface SocialReferralRefereeInviteApi {
    /** UUID of the organization that signed up via this referral link. */
    organization_id: string
    /** Current display name of the invited organization. */
    organization_name: string
    /** Whether this organization has sent its first ingested event. */
    first_event_sent: boolean
}

/**
 * Map of invited organization UUID (string) to `{"first_event_sent": boolean}`.
 */
export type SocialReferralApiRefereeState = { [key: string]: unknown }

export interface SocialReferralApi {
    readonly id: string
    readonly organization: string
    readonly user: number
    /** Map of invited organization UUID (string) to `{"first_event_sent": boolean}`. */
    referee_state?: SocialReferralApiRefereeState
    /** Invited organizations from referee_state with names resolved from the Organization table. */
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
