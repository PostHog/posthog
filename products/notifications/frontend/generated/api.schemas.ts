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
 * * `ticket` - TICKET
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
    Ticket: 'ticket',
} as const

/**
 * Optional structured payload for rich client-side rendering, specific to the notification type. For `web_analytics_digest`, holds the weekly metrics (visitors, pageviews, sessions, bounce rate, session duration with week-over-week change), top pages, and top sources used to render the digest card.
 * @nullable
 */
export type NotificationEventApiMetadata = { [key: string]: unknown } | null

export interface NotificationEventApi {
    /** Unique ID of the notification. */
    id: string
    /**
     * Project the notification belongs to. Null for organization-wide notifications.
     * @nullable
     */
    team_id: number | null
    /** Kind of notification, such as `comment_mention`. */
    notification_type: string
    /** `normal` or `critical`. */
    priority: string
    /** One-line summary shown in the notification list. */
    title: string
    /** Longer description. Can be empty. */
    body: string
    /** Whether the current user has read the notification. */
    read: boolean
    /**
     * When the current user read it, if they did.
     * @nullable
     */
    read_at: string | null
    /** Whether the current user has archived the notification. */
    archived: boolean
    /** Who the notification was sent to: `user`, `role`, `team` or `organization`. */
    target_type: string
    /** ID of the user, role, project or organization it was sent to. */
    target_id: string
    /**
     * Type of the object the notification is about, such as `insight`.
     * @nullable
     */
    resource_type: string | null
    /** ID of the object the notification is about. Can be empty. */
    resource_id: string
    /** Link to open for this notification. Can be empty. */
    source_url: string
    source_type: NotificationEventSourceTypeEnumApi | null
    /**
     * ID of the page to open, read with `source_type`.
     * @nullable
     */
    source_id: string | null
    /**
     * Optional structured payload for rich client-side rendering, specific to the notification type. For `web_analytics_digest`, holds the weekly metrics (visitors, pageviews, sessions, bounce rate, session duration with week-over-week change), top pages, and top sources used to render the digest card.
     * @nullable
     */
    metadata?: NotificationEventApiMetadata
    /** When the notification was created. */
    created_at: string
}

export interface PaginatedNotificationEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: NotificationEventApi[]
    /**
     * Pass as `before` to get the next page. Null on the last page.
     * @nullable
     */
    next_cursor?: string | null
}

export interface UnarchiveRequestApi {
    /** Also mark the notifications unread, to restore their state before the archive. */
    mark_unread?: boolean
}

export interface UpdatedCountApi {
    /** How many notifications changed. */
    updated: number
}

export interface ArchiveAllResponseApi {
    /** How many notifications changed. */
    updated: number
    /** IDs of the notifications this call archived, for an undo. */
    notification_ids: string[]
    /** The archived notifications that were unread, so an undo can mark them unread again. */
    unread_notification_ids: string[]
}

export interface BulkNotificationIdsRequestApi {
    /**
     * UUIDs of notification events to mark in bulk (max 500). Events the user is not a recipient of are silently skipped.
     * @maxItems 500
     */
    notification_ids: string[]
}

export interface BulkUnarchiveRequestApi {
    /**
     * UUIDs of notification events to mark in bulk (max 500). Events the user is not a recipient of are silently skipped.
     * @maxItems 500
     */
    notification_ids: string[]
    /** Also mark the notifications unread, to restore their state before the archive. */
    mark_unread?: boolean
}

export interface UnreadSummaryApi {
    /** Unread, non-archived notifications the user can see. */
    count: number
    /** Of those, how many were sent to the user by name or through one of their roles. */
    direct_count: number
    /** Whether any of those has `critical` priority. */
    has_critical: boolean
}

export type NotificationsListParams = {
    /**
     * When true, return only archived notifications; otherwise only non-archived ones (the default).
     */
    archived?: boolean
    /**
     * Cursor from `next_cursor` of the previous page. Returns notifications older than that page. Read and archive changes between pages never shift it, unlike `offset`.
     * @minLength 1
     */
    before?: string
    /**
     * ISO 8601 timestamp; only notifications created at or after this time.
     * @minLength 1
     */
    created_after?: string
    /**
     * ISO 8601 timestamp; only notifications created strictly before this time.
     * @minLength 1
     */
    created_before?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * Comma-separated notification types to include, such as `comment_mention,reminder`.
     * @minLength 1
     */
    notification_type?: string
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Only notifications with this priority: `normal` or `critical`.
     * @minLength 1
     */
    priority?: string
    /**
     * `false` returns only unread notifications, `true` only read ones. Leave out for both.
     * @nullable
     */
    read?: boolean | null
    /**
     * Only notifications about the object with this ID.
     * @minLength 1
     */
    resource_id?: string
    /**
     * Only notifications about this kind of object, such as `insight`.
     * @minLength 1
     */
    resource_type?: string
    /**
     * Only notifications sent to this recipient ID.
     * @minLength 1
     */
    target_id?: string
    /**
     * Comma-separated recipient kinds to include: `user`, `role`, `team`, `organization`.
     * @minLength 1
     */
    target_type?: string
    /**
     * Only notifications from this project, plus organization-wide ones, which belong to no project.
     */
    team_id?: number
}

export type NotificationsArchiveAllCreateParams = {
    /**
     * ISO 8601 timestamp; only notifications created at or after this time.
     * @minLength 1
     */
    created_after?: string
    /**
     * ISO 8601 timestamp; only notifications created strictly before this time.
     * @minLength 1
     */
    created_before?: string
    /**
     * Comma-separated notification types to include, such as `comment_mention,reminder`.
     * @minLength 1
     */
    notification_type?: string
    /**
     * Only notifications with this priority: `normal` or `critical`.
     * @minLength 1
     */
    priority?: string
    /**
     * `false` returns only unread notifications, `true` only read ones. Leave out for both.
     * @nullable
     */
    read?: boolean | null
    /**
     * Only notifications about the object with this ID.
     * @minLength 1
     */
    resource_id?: string
    /**
     * Only notifications about this kind of object, such as `insight`.
     * @minLength 1
     */
    resource_type?: string
    /**
     * Only notifications sent to this recipient ID.
     * @minLength 1
     */
    target_id?: string
    /**
     * Comma-separated recipient kinds to include: `user`, `role`, `team`, `organization`.
     * @minLength 1
     */
    target_type?: string
    /**
     * Only notifications from this project, plus organization-wide ones, which belong to no project.
     */
    team_id?: number
}

export type NotificationsMarkAllReadCreateParams = {
    /**
     * ISO 8601 timestamp; only notifications created at or after this time.
     * @minLength 1
     */
    created_after?: string
    /**
     * ISO 8601 timestamp; only notifications created strictly before this time.
     * @minLength 1
     */
    created_before?: string
    /**
     * Comma-separated notification types to include, such as `comment_mention,reminder`.
     * @minLength 1
     */
    notification_type?: string
    /**
     * Only notifications with this priority: `normal` or `critical`.
     * @minLength 1
     */
    priority?: string
    /**
     * `false` returns only unread notifications, `true` only read ones. Leave out for both.
     * @nullable
     */
    read?: boolean | null
    /**
     * Only notifications about the object with this ID.
     * @minLength 1
     */
    resource_id?: string
    /**
     * Only notifications about this kind of object, such as `insight`.
     * @minLength 1
     */
    resource_type?: string
    /**
     * Only notifications sent to this recipient ID.
     * @minLength 1
     */
    target_id?: string
    /**
     * Comma-separated recipient kinds to include: `user`, `role`, `team`, `organization`.
     * @minLength 1
     */
    target_type?: string
    /**
     * Only notifications from this project, plus organization-wide ones, which belong to no project.
     */
    team_id?: number
}
