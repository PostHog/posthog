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

export const NotificationsListResponse = /* @__PURE__ */ zod.object({
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
            read_at: zod.iso.datetime({}).nullable(),
            resource_type: zod.string().nullable(),
            resource_id: zod.string(),
            source_url: zod.string(),
            source_type: zod.string().nullable(),
            source_id: zod.string().nullable(),
            created_at: zod.iso.datetime({}),
        })
    ),
})
