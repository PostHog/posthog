/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ProductPushCampaignApi {
    /** Campaign id. Stable for the campaign's lifetime — key per-user dismissal state on it. */
    readonly id: string
    /** ProductKey value of the product being pushed (e.g. 'session_replay'). */
    readonly product_key: string
    /**
     * Sidebar path of the pushed product in the product catalog, for display resolution. Null when the key maps to no released catalog item.
     * @nullable
     */
    readonly product_path: string | null
    /**
     * Custom promo copy written by the TAM. Null means the client should use its default copy.
     * @nullable
     */
    readonly reason_text: string | null
    /** When this campaign started. */
    readonly started_at: string
    /**
     * When this campaign is planned to end.
     * @nullable
     */
    readonly ends_at: string | null
}

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

/**
 * The resolved person behind one side of a link, with a curated set of properties that mirror
 * the match signals (geo, device, campaign) so a reviewer can judge whether the link is plausible.
 */
export interface IdentityMatchingPersonApi {
    /** Distinct ID this person was resolved from. */
    distinct_id: string
    /**
     * When this person was first seen — person created_at (UTC).
     * @nullable
     */
    first_seen: string | null
    /**
     * When this person was last seen, when tracked — person last_seen_at (UTC).
     * @nullable
     */
    last_seen: string | null
    /**
     * Person's email, when set.
     * @nullable
     */
    email: string | null
    /**
     * Person's name property, when set.
     * @nullable
     */
    name: string | null
    /**
     * GeoIP city ($geoip_city_name).
     * @nullable
     */
    city: string | null
    /**
     * GeoIP country code ($geoip_country_code).
     * @nullable
     */
    country: string | null
    /**
     * Browser ($browser).
     * @nullable
     */
    browser: string | null
    /**
     * Operating system ($os).
     * @nullable
     */
    os: string | null
    /**
     * Device type, e.g. Desktop or Mobile ($device_type).
     * @nullable
     */
    device_type: string | null
    /**
     * Browser timezone ($timezone).
     * @nullable
     */
    timezone: string | null
    /**
     * Initial campaign source ($initial_utm_source).
     * @nullable
     */
    utm_source: string | null
    /**
     * Initial campaign medium ($initial_utm_medium).
     * @nullable
     */
    utm_medium: string | null
    /**
     * Initial campaign name ($initial_utm_campaign).
     * @nullable
     */
    utm_campaign: string | null
    /**
     * Initial referring domain ($initial_referring_domain).
     * @nullable
     */
    referring_domain: string | null
    /**
     * Initial Google click ID ($initial_gclid); present when the person arrived via a paid Google ad.
     * @nullable
     */
    gclid: string | null
}

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
    /** Resolved person behind the anonymous distinct ID; null when no profile exists for it. */
    orphan_person: IdentityMatchingPersonApi | null
    /** Resolved identified person behind the matched person key; null when no profile exists for it. */
    anchor_person: IdentityMatchingPersonApi | null
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
    /** Links from this model in the 'high' tier. */
    high_confidence: number
    /** Links from this model in the 'medium' tier. */
    medium_confidence: number
    /** Links from this model in the 'low' tier. */
    low_confidence: number
}

export interface IdentityMatchingRunApi {
    /** Identity matching run identifier (the Dagster run ID). */
    job_id: string
    /** When the run wrote its links (UTC). */
    computed_at: string
    /** Link counts per scoring model in this run. */
    models: IdentityMatchingRunModelCountApi[]
    /** Total links across all models in this run. */
    total_links: number
    /** Distinct anonymous visitors that were linked. */
    unique_orphans: number
    /** Links where a paid ad click was recovered for an anonymous visitor. */
    paid_touches: number
    /** Earliest link computed_at in the run (UTC). */
    first_link_at: string
    /** Latest link computed_at in the run (UTC). */
    last_link_at: string
}

export interface IdentityMatchingRunsResponseApi {
    /** Runs ordered by recency, most recent first. */
    results: IdentityMatchingRunApi[]
}

export type ProductPushCampaignActiveRetrieveParams = {
    /**
     * Team id of the project the caller is viewing. When that project already uses the campaign's product, the response is 204 so the promo isn't shown there.
     */
    team_id?: number
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
