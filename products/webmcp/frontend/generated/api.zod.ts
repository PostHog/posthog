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
 * @summary Run an exec command on the PostHog MCP server
 */
export const webmcpExecCreateBodyCommandMax = 100000

export const WebmcpExecCreateBody = /* @__PURE__ */ zod.object({
    command: zod
        .string()
        .max(webmcpExecCreateBodyCommandMax)
        .describe('The exec command to run, for example `search insights` or `call insight-get {...}`.'),
})
