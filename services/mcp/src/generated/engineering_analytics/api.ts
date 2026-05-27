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
        .describe("Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows."),
})

/**
 * How long pull requests take from open to merge. Returns median and p95 seconds and a PR count, either overall or split per author. Bots and drafts are excluded. This is a coarse metric: it combines draft and ready-for-review time, since the warehouse holds current state, not a transition history.
 */
export const EngineeringAnalyticsTimeToMergeParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const engineeringAnalyticsTimeToMergeQueryDateFromDefault = `-7d`
export const engineeringAnalyticsTimeToMergeQueryGroupByAuthorDefault = false

export const EngineeringAnalyticsTimeToMergeQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod
        .string()
        .default(engineeringAnalyticsTimeToMergeQueryDateFromDefault)
        .describe("Start of the window: a relative string like '-7d' or an ISO8601 timestamp. Defaults to '-7d'."),
    date_to: zod
        .string()
        .optional()
        .describe("End of the window: a relative string or ISO8601 timestamp. Omit for 'now'."),
    group_by_author: zod
        .boolean()
        .default(engineeringAnalyticsTimeToMergeQueryGroupByAuthorDefault)
        .describe('Split results per author handle instead of one overall bucket.'),
    repo: zod
        .string()
        .optional()
        .describe("Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows."),
})

/**
 * Which CI workflows are the long poles right now. Returns each GitHub Actions workflow with its run count, success rate, median and p95 duration, and last failure, slowest median first. Use this to answer 'what's slow in CI this week' or to check whether a known long-pole workflow is holding up a PR.
 */
export const EngineeringAnalyticsWorkflowReportParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const engineeringAnalyticsWorkflowReportQueryDateFromDefault = `-7d`

export const EngineeringAnalyticsWorkflowReportQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod
        .string()
        .default(engineeringAnalyticsWorkflowReportQueryDateFromDefault)
        .describe("Start of the window: a relative string like '-7d' or an ISO8601 timestamp. Defaults to '-7d'."),
    date_to: zod
        .string()
        .optional()
        .describe("End of the window: a relative string or ISO8601 timestamp. Omit for 'now'."),
    repo: zod
        .string()
        .optional()
        .describe("Optional 'owner/name' repository. In v1 this only labels the response; it does not filter rows."),
})
