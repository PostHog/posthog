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
 * Change one conversion goal in place. Fields you send are merged into the stored goal, the rest are kept, and the goal keeps its position in the list.
 * @summary Update conversion goal
 */
export const MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Add one conversion goal to the project. The server assigns conversion_goal_id and appends the goal to the end of the list, leaving existing goals untouched.
 * @summary Create conversion goal
 */
export const MarketingAnalyticsConversionGoalsCreateCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
