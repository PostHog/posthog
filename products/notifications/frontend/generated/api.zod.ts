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

export const NotificationsMarkReadBulkCreateBody = /* @__PURE__ */ zod.object({
    notification_ids: zod.array(zod.uuid()),
})

export const NotificationsMarkUnreadBulkCreateBody = /* @__PURE__ */ zod.object({
    notification_ids: zod.array(zod.uuid()),
})
