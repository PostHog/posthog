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
 * Lists health issues detected across all of this project's PostHog health checks (outdated SDKs, data warehouse sync failures, missing web analytics events, ingestion warnings, and more). Filter by status, severity, kind, or dismissed state.
 * @summary List health issues
 */
export const HealthIssuesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HealthIssuesListQueryParams = /* @__PURE__ */ zod.object({
    dismissed: zod
        .boolean()
        .optional()
        .describe('Filter by dismissed state. Omit to include both dismissed and non-dismissed issues.'),
    kind: zod.string().optional().describe("Only return issues from this check kind (e.g. 'sdk_outdated')."),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    severity: zod
        .string()
        .optional()
        .describe("Only return issues with this severity. One of: 'critical', 'warning', 'info'."),
    status: zod.string().optional().describe("Only return issues with this status. One of: 'active', 'resolved'."),
})

/**
 * Fetches a single health issue, enriched with the owning check's rendered explanation: a title, a one-line summary of what's wrong, a deep link to the relevant page, and remediation guidance for how to fix it.
 * @summary Get a health issue
 */
export const HealthIssuesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this health issue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Returns aggregated counts of active, non-dismissed health issues for the project, broken down by severity and by kind. Use for a quick overview of overall project health before drilling in with the list endpoint.
 * @summary Summarize active health issues
 */
export const HealthIssuesSummaryRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
