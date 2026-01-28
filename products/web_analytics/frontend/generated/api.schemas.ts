/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface WebAnalyticsBreakdownResponseApi {
    /**
     * URL for next page of results
     * @nullable
     */
    next?: string | null
    /** Array of breakdown items */
    results: unknown[]
}

export interface WebAnalyticsOverviewResponseApi {
    /** Unique visitors */
    visitors: number
    /** Total page views */
    views: number
    /** Total sessions */
    sessions: number
    /**
     * Bounce rate
     * @minimum 0
     * @maximum 1
     */
    bounce_rate: number
    /** Average session duration in seconds */
    session_duration: number
}

export type WebAnalyticsBreakdownRetrieveParams = {
    /**
     * Apply URL path cleaning
     */
    apply_path_cleaning?: boolean
    /**
 * Property to break down by

* `DeviceType` - DeviceType
* `Browser` - Browser
* `OS` - OS
* `Viewport` - Viewport
* `InitialReferringDomain` - InitialReferringDomain
* `InitialUTMSource` - InitialUTMSource
* `InitialUTMMedium` - InitialUTMMedium
* `InitialUTMCampaign` - InitialUTMCampaign
* `InitialUTMTerm` - InitialUTMTerm
* `InitialUTMContent` - InitialUTMContent
* `Country` - Country
* `Region` - Region
* `City` - City
* `InitialPage` - InitialPage
* `Page` - Page
* `ExitPage` - ExitPage
* `InitialChannelType` - InitialChannelType
 * @minLength 1
 */
    breakdown_by: WebAnalyticsBreakdownRetrieveBreakdownBy
    /**
     * Start date for the query (format: YYYY-MM-DD)
     */
    date_from: string
    /**
     * End date for the query (format: YYYY-MM-DD)
     */
    date_to: string
    /**
     * Filter out test accounts
     */
    filter_test_accounts?: boolean
    /**
     * Host to filter by (e.g. example.com)
     * @minLength 1
     * @nullable
     */
    host?: string | null
    /**
     * Number of results to return
     * @minimum 1
     * @maximum 1000
     */
    limit?: number
    /**
     * Number of results to skip
     * @minimum 0
     */
    offset?: number
}

export type WebAnalyticsBreakdownRetrieveBreakdownBy =
    (typeof WebAnalyticsBreakdownRetrieveBreakdownBy)[keyof typeof WebAnalyticsBreakdownRetrieveBreakdownBy]

export const WebAnalyticsBreakdownRetrieveBreakdownBy = {
    DeviceType: 'DeviceType',
    Browser: 'Browser',
    OS: 'OS',
    Viewport: 'Viewport',
    InitialReferringDomain: 'InitialReferringDomain',
    InitialUTMSource: 'InitialUTMSource',
    InitialUTMMedium: 'InitialUTMMedium',
    InitialUTMCampaign: 'InitialUTMCampaign',
    InitialUTMTerm: 'InitialUTMTerm',
    InitialUTMContent: 'InitialUTMContent',
    Country: 'Country',
    Region: 'Region',
    City: 'City',
    InitialPage: 'InitialPage',
    Page: 'Page',
    ExitPage: 'ExitPage',
    InitialChannelType: 'InitialChannelType',
} as const

export type WebAnalyticsOverviewRetrieveParams = {
    /**
     * Start date for the query (format: YYYY-MM-DD)
     */
    date_from: string
    /**
     * End date for the query (format: YYYY-MM-DD)
     */
    date_to: string
    /**
     * Filter out test accounts
     */
    filter_test_accounts?: boolean
    /**
     * Host to filter by (e.g. example.com)
     * @minLength 1
     * @nullable
     */
    host?: string | null
}
