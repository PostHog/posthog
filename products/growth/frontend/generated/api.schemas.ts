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
 * * `high` - high
 * * `medium` - medium
 * * `low` - low
 */
export type TierEnumApi = (typeof TierEnumApi)[keyof typeof TierEnumApi]

export const TierEnumApi = {
    High: 'high',
    Medium: 'medium',
    Low: 'low',
} as const

export interface IdentityMatchingLinkApi {
    /** Identity matching run that produced this link. */
    job_id: string
    /** Scoring model that produced the link, e.g. 'rules_v1' or 'logreg_v1'. */
    model_version: string
    /** Anonymous distinct ID that the model linked to an identified person. */
    orphan_distinct_id: string
    /** Canonical distinct ID representing the matched identified person. */
    anchor_person_key: string
    /** Link score: weighted rule points for 'rules_v1', a 0-1 probability for 'logreg_v1'. */
    score: number
    /** Score margin over the runner-up candidate person for this orphan. */
    margin: number
    /** Confidence tier derived from score thresholds.
     *
     * * `high` - high
     * * `medium` - medium
     * * `low` - low */
    tier: TierEnumApi
    /** When the link was computed (UTC). */
    computed_at: string
    /** Distinct (IP, day) combinations both sides were seen on. */
    shared_ip_days: number
    /** Distinct IPs both sides were seen on. */
    shared_ips: number
    /** Device count on the least crowded shared IP-day; small values suggest a household IP. */
    min_ip_block_size: number
    /** Both sides were seen in the same city. */
    geo_city_match: boolean
    /** Both sides reported the same timezone. */
    timezone_match: boolean
    /** Both sides reported the same browser language. */
    language_match: boolean
    /** A byte-identical user agent was seen on both sides. */
    ua_exact_match: boolean
    /** The orphan's traffic came from an in-app browser or webview. */
    orphan_is_webview: boolean
    /** The sides form a mobile + desktop device pair. */
    device_type_complement: boolean
    /** Number of days on which the two sides shared an IP. */
    days_overlap: number
    /** Average overlap (0-1) of pages visited by the two sides on shared IP-days. */
    avg_path_jaccard: number
    /** The orphan arrived via a paid click ID (gclid, li_fat_id, ...) inside the window. */
    orphan_paid_touch: boolean
    /** The matched person already had a paid click ID inside the window. */
    anchor_paid_touch: boolean
}

export interface IdentityMatchingLinksResponseApi {
    /** Links ordered by score, descending. */
    results: IdentityMatchingLinkApi[]
    /** Total links matching the filters, ignoring pagination. */
    count: number
}

export interface IdentityMatchingErrorApi {
    /** Human-readable explanation of why the request could not be served. */
    detail: string
}

export interface IdentityMatchingRunModelCountApi {
    /** Scoring model, e.g. 'rules_v1' or 'logreg_v1'. */
    model_version: string
    /** Number of links this model produced in the run. */
    link_count: number
}

export interface IdentityMatchingRunApi {
    /** Identity matching run identifier (the Dagster run ID). */
    job_id: string
    /** When the run wrote its links (UTC). */
    computed_at: string
    /** Link counts per scoring model in this run. */
    models: IdentityMatchingRunModelCountApi[]
}

export interface IdentityMatchingRunsResponseApi {
    /** Runs ordered by recency, most recent first. */
    results: IdentityMatchingRunApi[]
}

export type IdentityMatchingLinksListParams = {
    /**
     * Identity matching run to read. Defaults to the team's most recent run.
     */
    job_id?: string
    /**
     * Page size, at most 500.
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Only return links with a score at or above this.
     */
    min_score?: number
    /**
     * Only return links produced by this scoring model, e.g. 'rules_v1'.
     * @minLength 1
     */
    model_version?: string
    /**
     * Pagination offset.
     * @minimum 0
     */
    offset?: number
    /**
     * Case-insensitive substring match on the orphan distinct ID or the matched person key.
     * @minLength 1
     */
    search?: string
    /**
     * Only return links in this confidence tier.
     *
     * * `high` - high
     * * `medium` - medium
     * * `low` - low
     * @minLength 1
     */
    tier?: IdentityMatchingLinksListTier
}

export type IdentityMatchingLinksListTier =
    (typeof IdentityMatchingLinksListTier)[keyof typeof IdentityMatchingLinksListTier]

export const IdentityMatchingLinksListTier = {
    High: 'high',
    Medium: 'medium',
    Low: 'low',
} as const
