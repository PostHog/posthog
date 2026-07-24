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
    id: zod.uuid(),
    team_id: zod.number().nullable(),
    notification_type: zod.string(),
    priority: zod.string(),
    title: zod.string(),
    body: zod.string(),
    read: zod.boolean(),
    read_at: zod.iso.datetime({ offset: true }).nullable(),
    resource_type: zod.string().nullable(),
    resource_id: zod.string(),
    source_url: zod.string(),
    source_type: zod.union([
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
    ]),
    source_id: zod.string().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type NotificationEventApi = zod.input<typeof NotificationEventApi>
export type NotificationEventApiOutput = zod.output<typeof NotificationEventApi>

export const PaginatedNotificationEventListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            team_id: zod.number().nullable(),
            notification_type: zod.string(),
            priority: zod.string(),
            title: zod.string(),
            body: zod.string(),
            read: zod.boolean(),
            read_at: zod.iso.datetime({ offset: true }).nullable(),
            resource_type: zod.string().nullable(),
            resource_id: zod.string(),
            source_url: zod.string(),
            source_type: zod.union([
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
            ]),
            source_id: zod.string().nullable(),
            created_at: zod.iso.datetime({ offset: true }),
        })
    ),
})

export type PaginatedNotificationEventListApi = zod.input<typeof PaginatedNotificationEventListApi>
export type PaginatedNotificationEventListApiOutput = zod.output<typeof PaginatedNotificationEventListApi>
