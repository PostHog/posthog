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
 * CRUD for referral share links under an organization.
 * @summary Create social referral
 */
export const SocialReferralsCreateBody = /* @__PURE__ */ zod.object({
    referee_state: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Map of invited organization UUID (string) to `{\"first_event_sent\": boolean}`.'),
})
