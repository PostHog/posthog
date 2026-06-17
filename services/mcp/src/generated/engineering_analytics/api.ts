/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
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
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * Open pull requests plus any merged or closed since date_from (default -30d), newest first, each with its head-SHA CI rollup. The list is capped; when more match, `truncated` is true and the ci_cards counts can exceed it. open_to_merge_seconds is coarse — it fuses draft and ready-for-review time; CI counts can lag until late completions settle.
 */
export const EngineeringAnalyticsPullRequestsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsPullRequestsQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.string().optional().describe("Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d."),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})

/**
 * Per-workflow CI health over a window (default last 30 days, maximum 366 days): run count, success rate, p50/p95 duration over completed runs, last failure time, and a zero-filled daily run history. Use this for 'is CI getting slower' and 'which workflow is the long pole'; compare two windows to get a trend.
 */
export const EngineeringAnalyticsWorkflowHealthParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EngineeringAnalyticsWorkflowHealthQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.string().optional().describe("Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d."),
    date_to: zod.string().optional().describe('Window end: relative or ISO8601. Defaults to now.'),
    source_id: zod
        .string()
        .optional()
        .describe(
            'Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub source when the team has more than one.'
        ),
})
