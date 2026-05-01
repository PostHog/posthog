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
 * * `error` - error
 * `warning` - warning
 */
export type UtmIssueSeverityEnumApi = (typeof UtmIssueSeverityEnumApi)[keyof typeof UtmIssueSeverityEnumApi]

export const UtmIssueSeverityEnumApi = {
    Error: 'error',
    Warning: 'warning',
} as const

export interface UtmIssueApi {
    /** The UTM field with the issue (e.g. utm_campaign, utm_source) */
    field: string
    /** Issue severity level

* `error` - error
* `warning` - warning */
    severity: UtmIssueSeverityEnumApi
    /** Human-readable description of the issue */
    message: string
}

export interface CampaignAuditResultApi {
    /** Campaign name from the ad platform */
    campaign_name: string
    /** Campaign ID from the ad platform */
    campaign_id: string
    /** Integration source name (e.g. google, meta) */
    source_name: string
    /** Total spend for this campaign in the period */
    spend: number
    /** Total clicks for this campaign */
    clicks: number
    /** Total impressions for this campaign */
    impressions: number
    /** Whether matching UTM pageview events were found */
    has_utm_events: boolean
    /** Number of matching UTM pageview events */
    event_count: number
    /** List of detected UTM configuration issues */
    issues: UtmIssueApi[]
}

/**
 * * `none` - none
 * `auto` - auto
 * `mapped` - mapped
 */
export type SourceMatchEnumApi = (typeof SourceMatchEnumApi)[keyof typeof SourceMatchEnumApi]

export const SourceMatchEnumApi = {
    None: 'none',
    Auto: 'auto',
    Mapped: 'mapped',
} as const

export interface UtmEventApi {
    /** UTM campaign value from pageview events */
    utm_campaign: string
    /** UTM source value from pageview events */
    utm_source: string
    /** Number of pageview events with this UTM combination */
    event_count: number
    /** How utm_campaign matched: none, auto (direct name/id), or mapped (manual mapping)

* `none` - none
* `auto` - auto
* `mapped` - mapped */
    campaign_match: SourceMatchEnumApi
    /** How utm_source matched: none, auto (default source), or mapped (custom mapping)

* `none` - none
* `auto` - auto
* `mapped` - mapped */
    source_match: SourceMatchEnumApi
    /**
     * Name of the matched campaign, if any
     * @nullable
     */
    matched_campaign: string | null
}

export interface UtmAuditResponseApi {
    /** Total number of campaigns with spend */
    total_campaigns: number
    /** Number of campaigns with UTM issues */
    campaigns_with_issues: number
    /** Number of campaigns without issues */
    campaigns_without_issues: number
    /** Total spend on campaigns with UTM issues */
    total_spend_at_risk: number
    /** Audit results per campaign */
    results: CampaignAuditResultApi[]
    /** All UTM events with match status */
    all_utm_events: UtmEventApi[]
}

export type MarketingAnalyticsUtmAuditRetrieveParams = {
    /**
     * Start date for the audit period
     * @minLength 1
     */
    date_from?: string
    /**
     * End date for the audit period
     * @minLength 1
     * @nullable
     */
    date_to?: string | null
}
