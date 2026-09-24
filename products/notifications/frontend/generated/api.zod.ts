/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Add the primary key as a final ordering term to each queryset that the viewset pages.
 *
 * TeamAndOrgViewSetMixin inherits this. A viewset without that mixin inherits it directly.
 */
export const notificationsArchiveBulkCreateBodyNotificationIdsMax = 500

export const NotificationsArchiveBulkCreateBody = /* @__PURE__ */ zod.object({
    notification_ids: zod
        .array(zod.uuid())
        .max(notificationsArchiveBulkCreateBodyNotificationIdsMax)
        .describe(
            'UUIDs of notification events to mark in bulk (max 500). Events the user is not a recipient of are silently skipped.'
        ),
})

/**
 * Add the primary key as a final ordering term to each queryset that the viewset pages.
 *
 * TeamAndOrgViewSetMixin inherits this. A viewset without that mixin inherits it directly.
 */
export const notificationsMarkReadBulkCreateBodyNotificationIdsMax = 500

export const NotificationsMarkReadBulkCreateBody = /* @__PURE__ */ zod.object({
    notification_ids: zod
        .array(zod.uuid())
        .max(notificationsMarkReadBulkCreateBodyNotificationIdsMax)
        .describe(
            'UUIDs of notification events to mark in bulk (max 500). Events the user is not a recipient of are silently skipped.'
        ),
})

/**
 * Add the primary key as a final ordering term to each queryset that the viewset pages.
 *
 * TeamAndOrgViewSetMixin inherits this. A viewset without that mixin inherits it directly.
 */
export const notificationsMarkUnreadBulkCreateBodyNotificationIdsMax = 500

export const NotificationsMarkUnreadBulkCreateBody = /* @__PURE__ */ zod.object({
    notification_ids: zod
        .array(zod.uuid())
        .max(notificationsMarkUnreadBulkCreateBodyNotificationIdsMax)
        .describe(
            'UUIDs of notification events to mark in bulk (max 500). Events the user is not a recipient of are silently skipped.'
        ),
})
