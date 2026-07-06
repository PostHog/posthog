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
 * * `replay` - REPLAY
 * * `notebook` - NOTEBOOK
 * * `insight` - INSIGHT
 * * `feature_flag` - FEATURE_FLAG
 * * `dashboard` - DASHBOARD
 * * `survey` - SURVEY
 * * `experiment` - EXPERIMENT
 * * `error_tracking` - ERROR_TRACKING
 * * `customer_analytics` - CUSTOMER_ANALYTICS
 */
export type NotificationEventSourceTypeEnumApi =
    (typeof NotificationEventSourceTypeEnumApi)[keyof typeof NotificationEventSourceTypeEnumApi]

export const NotificationEventSourceTypeEnumApi = {
    Replay: 'replay',
    Notebook: 'notebook',
    Insight: 'insight',
    FeatureFlag: 'feature_flag',
    Dashboard: 'dashboard',
    Survey: 'survey',
    Experiment: 'experiment',
    ErrorTracking: 'error_tracking',
    CustomerAnalytics: 'customer_analytics',
} as const

/**
 * Optional structured payload for rich client-side rendering, specific to the notification type. For `web_analytics_digest`, holds the weekly metrics (visitors, pageviews, sessions, bounce rate, session duration with week-over-week change), top pages, and top sources used to render the digest card.
 * @nullable
 */
export type NotificationEventApiMetadata = { [key: string]: unknown } | null

export interface NotificationEventApi {
    id: string
    /** @nullable */
    team_id: number | null
    notification_type: string
    priority: string
    title: string
    body: string
    read: boolean
    /** @nullable */
    read_at: string | null
    target_type: string
    target_id: string
    /** @nullable */
    resource_type: string | null
    resource_id: string
    source_url: string
    source_type: NotificationEventSourceTypeEnumApi | null
    /** @nullable */
    source_id: string | null
    /**
     * Optional structured payload for rich client-side rendering, specific to the notification type. For `web_analytics_digest`, holds the weekly metrics (visitors, pageviews, sessions, bounce rate, session duration with week-over-week change), top pages, and top sources used to render the digest card.
     * @nullable
     */
    metadata?: NotificationEventApiMetadata
    created_at: string
}

export interface PaginatedNotificationEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: NotificationEventApi[]
}

export interface BulkNotificationIdsRequestApi {
    /**
     * UUIDs of notification events to mark in bulk (max 500). Events the user is not a recipient of are silently skipped.
     * @maxItems 500
     */
    notification_ids: string[]
}

export type NotificationsListParams = {
    /**
     * ISO 8601 timestamp; only events at or after this time
     */
    created_after?: string
    /**
     * ISO 8601 timestamp; only events strictly before this time
     */
    created_before?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * Filter by notification type
     */
    notification_type?: string
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by the ID of the resource the notification refers to
     */
    resource_id?: string
    /**
     * Filter by the type of the resource the notification refers to (e.g. `insight`, `dashboard`)
     */
    resource_type?: string
    /**
     * Filter by recipient target ID (e.g. a user ID)
     */
    target_id?: string
    /**
     * Filter by recipient target type (e.g. `user`, `team`)
     */
    target_type?: string
}
