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
 * List or update the secure connections approved for CDP destinations.
 */
export const SecureConnectionsCdpApprovalsCreateBody = /* @__PURE__ */ zod.object({
    connection_id: zod.uuid(),
    approved: zod.boolean(),
})
