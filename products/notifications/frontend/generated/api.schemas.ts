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
 * `notebook` - NOTEBOOK
 * `insight` - INSIGHT
 * `feature_flag` - FEATURE_FLAG
 * `dashboard` - DASHBOARD
 * `survey` - SURVEY
 * `experiment` - EXPERIMENT
 * `error_tracking` - ERROR_TRACKING
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
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

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
    /** @nullable */
    resource_type: string | null
    resource_id: string
    source_url: string
    source_type: NotificationEventSourceTypeEnumApi | NullEnumApi | null
    /** @nullable */
    source_id: string | null
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

export type NotificationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
