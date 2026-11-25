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

export const meepTopicsCreateBodyTitleMax = 255

export const MeepTopicsCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(meepTopicsCreateBodyTitleMax),
    mission: zod.string(),
})

export const MeepTopicsConversationCreateBody = /* @__PURE__ */ zod.object({
    task_id: zod.uuid(),
})
