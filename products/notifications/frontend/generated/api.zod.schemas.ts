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
    .enum([
        'replay',
        'notebook',
        'insight',
        'feature_flag',
        'dashboard',
        'survey',
        'experiment',
        'error_tracking',
        'customer_analytics',
        'ticket',
    ])
    .describe(
        '\* `replay` - REPLAY\n\* `notebook` - NOTEBOOK\n\* `insight` - INSIGHT\n\* `feature_flag` - FEATURE_FLAG\n\* `dashboard` - DASHBOARD\n\* `survey` - SURVEY\n\* `experiment` - EXPERIMENT\n\* `error_tracking` - ERROR_TRACKING\n\* `customer_analytics` - CUSTOMER_ANALYTICS\n\* `ticket` - TICKET'
    )

export type NotificationEventSourceTypeEnumApi = zod.input<typeof NotificationEventSourceTypeEnumApi>
export type NotificationEventSourceTypeEnumApiOutput = zod.output<typeof NotificationEventSourceTypeEnumApi>

export const NotificationEventApi = zod.object({
    id: zod.uuid(),
    team_id: zod.number().nullable(),
    notification_type: zod.string(),
    priority: zod.string(),
    title: zod.string(),
    body: zod.string(),
    read: zod.boolean(),
    read_at: zod.iso.datetime({ offset: true }).nullable(),
    target_type: zod.string(),
    target_id: zod.string(),
    resource_type: zod.string().nullable(),
    resource_id: zod.string(),
    source_url: zod.string(),
    source_type: zod.union([NotificationEventSourceTypeEnumApi, zod.null()]),
    source_id: zod.string().nullable(),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe(
            'Optional structured payload for rich client-side rendering, specific to the notification type. For `web_analytics_digest`, holds the weekly metrics (visitors, pageviews, sessions, bounce rate, session duration with week-over-week change), top pages, and top sources used to render the digest card.'
        ),
    created_at: zod.iso.datetime({ offset: true }),
})

export type NotificationEventApi = zod.input<typeof NotificationEventApi>
export type NotificationEventApiOutput = zod.output<typeof NotificationEventApi>

export const PaginatedNotificationEventListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(NotificationEventApi),
})

export type PaginatedNotificationEventListApi = zod.input<typeof PaginatedNotificationEventListApi>
export type PaginatedNotificationEventListApiOutput = zod.output<typeof PaginatedNotificationEventListApi>

export const bulkNotificationIdsRequestApiNotificationIdsMax = 500

export const BulkNotificationIdsRequestApi = zod.object({
    notification_ids: zod
        .array(zod.uuid())
        .max(bulkNotificationIdsRequestApiNotificationIdsMax)
        .describe(
            'UUIDs of notification events to mark in bulk (max 500). Events the user is not a recipient of are silently skipped.'
        ),
})

export type BulkNotificationIdsRequestApi = zod.input<typeof BulkNotificationIdsRequestApi>
export type BulkNotificationIdsRequestApiOutput = zod.output<typeof BulkNotificationIdsRequestApi>
