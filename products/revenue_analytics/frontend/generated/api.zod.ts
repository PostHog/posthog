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
export const RevenueAnalyticsJoinsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().describe('True creates the person join for the project, false removes it.'),
})
