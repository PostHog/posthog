/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * The timeline of a single pull request: header plus ordered events (opened, CI started/finished, merged or closed). Use this to answer 'where is this PR stuck and what happened to it'. This is a partial view: review and comment events are not yet available.
 */
export const EngineeringAnalyticsPrLifecycleParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsPrLifecycleQueryParams = /* @__PURE__ */ zod.object({
    pr_number: zod.number().describe('Pull request number to inspect.'),
    repo: zod
        .string()
        .optional()
        .describe(
            "Optional 'owner/name' repository to disambiguate when the PR number exists in more than one connected repo."
        ),
})
