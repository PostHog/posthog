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
 * Read serializer for `AgentNoticeData` facade DTOs.
 */
export interface AgentNoticeApi {
    /** Unique identifier of the notice. */
    id: string
    /** Notice text intended for the project's AI agent sessions. */
    message: string
    /**
     * Optional feature flag key gating delivery; when set, deliver only if the flag evaluates true.
     * @nullable
     */
    feature_flag_key: string | null
    /** When the notice becomes active. */
    starts_at: string
    /** When the notice stops being delivered. */
    expires_at: string
    /** When the notice was created. */
    created_at: string
}

/**
 * * `replay` - REPLAY
 * * `notebook` - NOTEBOOK
 * * `insight` - INSIGHT
 * * `feature_flag` - FEATURE_FLAG
 * * `dashboard` - DASHBOARD
 * * `survey` - SURVEY
 * * `experiment` - EXPERIMENT
 * * `error_tracking` - ERROR_TRACKING
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
