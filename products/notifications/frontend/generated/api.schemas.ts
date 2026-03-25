/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface NotificationEventApi {
    id: string
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
 * * `comment_mention` - COMMENT_MENTION
 * `alert_firing` - ALERT_FIRING
 * `approval_requested` - APPROVAL_REQUESTED
 * `approval_resolved` - APPROVAL_RESOLVED
 * `pipeline_failure` - PIPELINE_FAILURE
 * `issue_assigned` - ISSUE_ASSIGNED
 */
export type NotificationTypeEnumApi = (typeof NotificationTypeEnumApi)[keyof typeof NotificationTypeEnumApi]

export const NotificationTypeEnumApi = {
    CommentMention: 'comment_mention',
    AlertFiring: 'alert_firing',
    ApprovalRequested: 'approval_requested',
    ApprovalResolved: 'approval_resolved',
    PipelineFailure: 'pipeline_failure',
    IssueAssigned: 'issue_assigned',
} as const

/**
 * * `normal` - NORMAL
 * `critical` - CRITICAL
 */
export type SendTestNotificationPriorityEnumApi =
    (typeof SendTestNotificationPriorityEnumApi)[keyof typeof SendTestNotificationPriorityEnumApi]

export const SendTestNotificationPriorityEnumApi = {
    Normal: 'normal',
    Critical: 'critical',
} as const

export interface SendTestNotificationApi {
    notification_type: NotificationTypeEnumApi
    priority?: SendTestNotificationPriorityEnumApi
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
