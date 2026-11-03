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
 * @summary Set the default project for the Slack workspace of a Slack app install
 */
export const SlackAppWorkspaceSetupDefaultProjectCreateBody = /* @__PURE__ */ zod.object({
    integration_id: zod
        .number()
        .describe('ID of the Slack integration of the project that becomes the workspace default.'),
})
