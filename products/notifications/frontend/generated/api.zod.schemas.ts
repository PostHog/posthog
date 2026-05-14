/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const NotificationEventSourceTypeEnumApi = zod
    .enum(['replay', 'notebook', 'insight', 'feature_flag', 'dashboard', 'survey', 'experiment', 'error_tracking'])
    .describe(
        '\* `replay` - REPLAY\n\* `notebook` - NOTEBOOK\n\* `insight` - INSIGHT\n\* `feature_flag` - FEATURE_FLAG\n\* `dashboard` - DASHBOARD\n\* `survey` - SURVEY\n\* `experiment` - EXPERIMENT\n\* `error_tracking` - ERROR_TRACKING'
    )

export type NotificationEventSourceTypeEnumApi = zod.input<typeof NotificationEventSourceTypeEnumApi>
export type NotificationEventSourceTypeEnumApiOutput = zod.output<typeof NotificationEventSourceTypeEnumApi>

export const NotificationEventApi = zod.object({
    id: zod.uuid().describe('Unique identifier for this notification event.'),
    team_id: zod
        .number()
        .nullable()
        .describe('ID of the team this notification belongs to, or null when the notification is organization-scoped.'),
    notification_type: zod
        .string()
        .describe(
            "What kind of notification this is — for example 'alert_firing', 'comment_mention', 'issue_assigned', 'approval_requested', 'approval_resolved', 'experiment_concluded', or 'concierge'."
        ),
    priority: zod
        .string()
        .describe("Delivery priority: 'normal' (popover only) or 'critical' (popover plus persistent toast)."),
    title: zod.string().describe('Short headline shown to the user in the notification UI.'),
    body: zod.string().describe('Full message body shown beneath the title.'),
    read: zod.boolean().describe('Whether the current user has marked this notification as read.'),
    read_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the current user marked this notification as read, or null if still unread.'),
    resource_type: zod
        .string()
        .nullable()
        .describe(
            "Type of resource this notification points at, e.g. 'dashboard', 'insight', 'alert', 'comment'. Null when the notification is not tied to a specific resource."
        ),
    resource_id: zod.string().describe('ID of the linked resource (matches resource_type). Empty when not applicable.'),
    source_url: zod.string().describe('Relative PostHog URL to navigate to when the user clicks the notification.'),
    source_type: zod
        .union([
            zod
                .enum([
                    'replay',
                    'notebook',
                    'insight',
                    'feature_flag',
                    'dashboard',
                    'survey',
                    'experiment',
                    'error_tracking',
                ])
                .describe(
                    '\* `replay` - REPLAY\n\* `notebook` - NOTEBOOK\n\* `insight` - INSIGHT\n\* `feature_flag` - FEATURE_FLAG\n\* `dashboard` - DASHBOARD\n\* `survey` - SURVEY\n\* `experiment` - EXPERIMENT\n\* `error_tracking` - ERROR_TRACKING'
                ),
            zod.null(),
        ])
        .describe(
            "Subsystem that produced the notification (e.g. 'alerts', 'comments'). Null if unattributed.\n\n\* `replay` - REPLAY\n\* `notebook` - NOTEBOOK\n\* `insight` - INSIGHT\n\* `feature_flag` - FEATURE_FLAG\n\* `dashboard` - DASHBOARD\n\* `survey` - SURVEY\n\* `experiment` - EXPERIMENT\n\* `error_tracking` - ERROR_TRACKING"
        ),
    source_id: zod
        .string()
        .nullable()
        .describe('ID of the producing record in the source subsystem (e.g. alert ID, comment ID).'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the notification was created, in ISO 8601 format.'),
})

export type NotificationEventApi = zod.input<typeof NotificationEventApi>
export type NotificationEventApiOutput = zod.output<typeof NotificationEventApi>

export const PaginatedNotificationEventListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid().describe('Unique identifier for this notification event.'),
            team_id: zod
                .number()
                .nullable()
                .describe(
                    'ID of the team this notification belongs to, or null when the notification is organization-scoped.'
                ),
            notification_type: zod
                .string()
                .describe(
                    "What kind of notification this is — for example 'alert_firing', 'comment_mention', 'issue_assigned', 'approval_requested', 'approval_resolved', 'experiment_concluded', or 'concierge'."
                ),
            priority: zod
                .string()
                .describe("Delivery priority: 'normal' (popover only) or 'critical' (popover plus persistent toast)."),
            title: zod.string().describe('Short headline shown to the user in the notification UI.'),
            body: zod.string().describe('Full message body shown beneath the title.'),
            read: zod.boolean().describe('Whether the current user has marked this notification as read.'),
            read_at: zod.iso
                .datetime({ offset: true })
                .nullable()
                .describe('When the current user marked this notification as read, or null if still unread.'),
            resource_type: zod
                .string()
                .nullable()
                .describe(
                    "Type of resource this notification points at, e.g. 'dashboard', 'insight', 'alert', 'comment'. Null when the notification is not tied to a specific resource."
                ),
            resource_id: zod
                .string()
                .describe('ID of the linked resource (matches resource_type). Empty when not applicable.'),
            source_url: zod
                .string()
                .describe('Relative PostHog URL to navigate to when the user clicks the notification.'),
            source_type: zod
                .union([
                    zod
                        .enum([
                            'replay',
                            'notebook',
                            'insight',
                            'feature_flag',
                            'dashboard',
                            'survey',
                            'experiment',
                            'error_tracking',
                        ])
                        .describe(
                            '\* `replay` - REPLAY\n\* `notebook` - NOTEBOOK\n\* `insight` - INSIGHT\n\* `feature_flag` - FEATURE_FLAG\n\* `dashboard` - DASHBOARD\n\* `survey` - SURVEY\n\* `experiment` - EXPERIMENT\n\* `error_tracking` - ERROR_TRACKING'
                        ),
                    zod.null(),
                ])
                .describe(
                    "Subsystem that produced the notification (e.g. 'alerts', 'comments'). Null if unattributed.\n\n\* `replay` - REPLAY\n\* `notebook` - NOTEBOOK\n\* `insight` - INSIGHT\n\* `feature_flag` - FEATURE_FLAG\n\* `dashboard` - DASHBOARD\n\* `survey` - SURVEY\n\* `experiment` - EXPERIMENT\n\* `error_tracking` - ERROR_TRACKING"
                ),
            source_id: zod
                .string()
                .nullable()
                .describe('ID of the producing record in the source subsystem (e.g. alert ID, comment ID).'),
            created_at: zod.iso
                .datetime({ offset: true })
                .describe('When the notification was created, in ISO 8601 format.'),
        })
    ),
})

export type PaginatedNotificationEventListApi = zod.input<typeof PaginatedNotificationEventListApi>
export type PaginatedNotificationEventListApiOutput = zod.output<typeof PaginatedNotificationEventListApi>
