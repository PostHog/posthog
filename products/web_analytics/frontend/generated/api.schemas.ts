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
 * * `Up` - Up
 * `Down` - Down
 */
export type DirectionEnumApi = (typeof DirectionEnumApi)[keyof typeof DirectionEnumApi]

export const DirectionEnumApi = {
    Up: 'Up',
    Down: 'Down',
} as const

export interface WoWChangeApi {
    /** Absolute percentage change, rounded to nearest integer. */
    percent: number
    /** Direction of the change relative to the prior period.

* `Up` - Up
* `Down` - Down */
    direction: DirectionEnumApi
    /** Hex color indicating whether the change is a positive or negative signal. */
    color: string
    /** Short label, e.g. 'Up 12%'. */
    text: string
    /** Verbose label, e.g. 'Up 12% from prior period'. */
    long_text: string
}

export interface NumericMetricApi {
    /** Value for the most recent period. */
    current: number
    /**
     * Value for the prior period, if available.
     * @nullable
     */
    previous: number | null
    /** Period-over-period change, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface DurationMetricApi {
    /** Human-readable duration, e.g. '2m 34s'. */
    current: string
    /**
     * Prior-period duration, e.g. '2m 10s'.
     * @nullable
     */
    previous: string | null
    /** Period-over-period change, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface TopPageApi {
    /** Host for the page, if recorded. */
    host: string
    /** URL path. */
    path: string
    /** Unique visitors in the period. */
    visitors: number
    /** Period-over-period change in visitors, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface TopSourceApi {
    /** Initial referring domain. */
    name: string
    /** Unique visitors from this source. */
    visitors: number
    /** Period-over-period change in visitors, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface GoalApi {
    /** Goal name (action name). */
    name: string
    /** Total conversions in the period. */
    conversions: number
    /** Period-over-period change in conversions, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface WeeklyDigestResponseApi {
    /** Unique visitors. */
    visitors: NumericMetricApi
    /** Total pageviews. */
    pageviews: NumericMetricApi
    /** Total sessions. */
    sessions: NumericMetricApi
    /** Bounce rate (0–100). */
    bounce_rate: NumericMetricApi
    /** Average session duration. */
    avg_session_duration: DurationMetricApi
    /** Top 5 pages by unique visitors. */
    top_pages: TopPageApi[]
    /** Top 5 traffic sources by unique visitors. */
    top_sources: TopSourceApi[]
    /** Goal conversions. */
    goals: GoalApi[]
    /** Link to the Web analytics dashboard for this project. */
    dashboard_url: string
}

export type WebAnalyticsWeeklyDigestParams = {
    /**
     * When true (default), include period-over-period change for each metric comparing against the prior equal-length period. Set to false to skip the comparison query (faster).
     */
    compare?: boolean
    /**
     * Lookback window in days (1–90). Defaults to 7.
     */
    days?: number
}
