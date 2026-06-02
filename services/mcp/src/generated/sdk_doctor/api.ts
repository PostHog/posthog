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
 * Returns a pre-digested health assessment of the PostHog SDKs the project is using. Covers which SDKs are current vs outdated (smart-semver rules with grace periods and traffic-percentage thresholds), per-version breakdown, and a human-readable reason for each assessment. Use this to diagnose SDK version issues, surface upgrade recommendations, or check overall SDK health.
 * @summary Get SDK health report for a project
 */
export const SdkDoctorReportRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SdkDoctorReportRetrieveQueryParams = /* @__PURE__ */ zod.object({
    force_refresh: zod
        .boolean()
        .optional()
        .describe(
            'When true, bypasses the Redis cache and re-queries ClickHouse for SDK usage. Use sparingly — data is refreshed every 12 hours by a background job.'
        ),
})
