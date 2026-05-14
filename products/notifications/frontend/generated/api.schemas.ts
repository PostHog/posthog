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

export interface NotificationEventApi {
    /** Unique identifier for this notification event. */
    id: string
    /**
     * ID of the team this notification belongs to, or null when the notification is organization-scoped.
     * @nullable
     */
    team_id: number | null
    /** What kind of notification this is — for example 'alert_firing', 'comment_mention', 'issue_assigned', 'approval_requested', 'approval_resolved', 'experiment_concluded', or 'concierge'. */
    notification_type: string
    /** Delivery priority: 'normal' (popover only) or 'critical' (popover plus persistent toast). */
    priority: string
    /** Short headline shown to the user in the notification UI. */
    title: string
    /** Full message body shown beneath the title. */
    body: string
    /** Whether the current user has marked this notification as read. */
    read: boolean
    /**
     * When the current user marked this notification as read, or null if still unread.
     * @nullable
     */
    read_at: string | null
    /**
     * Type of resource this notification points at, e.g. 'dashboard', 'insight', 'alert', 'comment'. Null when the notification is not tied to a specific resource.
     * @nullable
     */
    resource_type: string | null
    /** ID of the linked resource (matches resource_type). Empty when not applicable. */
    resource_id: string
    /** Relative PostHog URL to navigate to when the user clicks the notification. */
    source_url: string
    /** Subsystem that produced the notification (e.g. 'alerts', 'comments'). Null if unattributed.

  * `replay` - REPLAY
  * `notebook` - NOTEBOOK
  * `insight` - INSIGHT
  * `feature_flag` - FEATURE_FLAG
  * `dashboard` - DASHBOARD
  * `survey` - SURVEY
  * `experiment` - EXPERIMENT
  * `error_tracking` - ERROR_TRACKING */
    source_type: NotificationEventSourceTypeEnumApi | null
    /**
     * ID of the producing record in the source subsystem (e.g. alert ID, comment ID).
     * @nullable
     */
    source_id: string | null
    /** When the notification was created, in ISO 8601 format. */
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

/**
 * * `normal` - NORMAL
 * `critical` - CRITICAL
 */
export type SendConciergeNotificationPriorityEnumApi =
    (typeof SendConciergeNotificationPriorityEnumApi)[keyof typeof SendConciergeNotificationPriorityEnumApi]

export const SendConciergeNotificationPriorityEnumApi = {
    Normal: 'normal',
    Critical: 'critical',
} as const

/**
 * * `envelope` - envelope
 * `scroll` - scroll
 * `galactic` - galactic
 */
export type NotificationStyleEnumApi = (typeof NotificationStyleEnumApi)[keyof typeof NotificationStyleEnumApi]

export const NotificationStyleEnumApi = {
    Envelope: 'envelope',
    Scroll: 'scroll',
    Galactic: 'galactic',
} as const

export interface SendConciergeNotificationApi {
    /**
     * IDs of the PostHog users who should receive this notification. Each user will receive the notification in their current project. Users without a current team are skipped.
     * @minItems 1
     */
    target_user_ids: number[]
    /**
     * Short headline shown to the user in the notification UI (max 255 characters).
     * @maxLength 255
     */
    title: string
    /** Main message body shown beneath the title. Can be left blank if the long-form wizard text carries the message. */
    body: string
    /** Delivery priority: 'normal' (popover only) or 'critical' (popover plus persistent toast).

  * `normal` - NORMAL
  * `critical` - CRITICAL */
    priority?: SendConciergeNotificationPriorityEnumApi
    /** Visual style for the notification: 'envelope', 'scroll', or 'galactic'.

  * `envelope` - envelope
  * `scroll` - scroll
  * `galactic` - galactic */
    notification_style?: NotificationStyleEnumApi
    /** Optional skill identifier used by the wizard UI to render an associated capability for the user. */
    skill?: string
    /** Optional long-form text shown in the notification wizard expanded view. */
    long_form_wizard_text?: string
}

export interface SendConciergeNotificationSkippedApi {
    /** ID of the user that was skipped. */
    user_id: number
    /** Human-readable reason the notification was not delivered to this user. */
    reason: string
}

export interface SendConciergeNotificationResponseApi {
    /** Number of users that successfully received the notification. */
    sent: number
    /** List of users that were skipped, with the reason for each (e.g. no current team, suppressed by feature flag). */
    skipped: SendConciergeNotificationSkippedApi[]
    /** IDs of the NotificationEvent rows that were created, one per successfully delivered user. */
    notification_event_ids: string[]
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
