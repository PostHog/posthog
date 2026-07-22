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
 * Recent ReviewHog reviews on this project.
 */
export const ReviewHogReviewsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ReviewHogReviewsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .optional()
        .describe(
            'Maximum rows to return. The list grows this instead of paging by offset — in-progress rows reorder the list between refreshes, so offset pages would shift under the reader.'
        ),
    scope: zod
        .enum(['mine', 'everyone'])
        .optional()
        .describe(
            "Whose reviews to list: `mine` for reviews of the requesting user's pull requests (the default), `everyone` for every review on this project."
        ),
})

/**
 * Recent ReviewHog reviews on this project.
 */
export const ReviewHogReviewsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('The review report id, for fetching the review detail.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Recent ReviewHog reviews on this project.
 */
export const ReviewHogReviewsTriggerCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ReviewHogReviewsTriggerCreateBody = /* @__PURE__ */ zod.object({
    pr_url: zod
        .string()
        .describe(
            "GitHub pull request URL to review, e.g. 'https://github.com/PostHog/posthog.com/pull/123'. The repository must be accessible to the project's GitHub App installation."
        ),
})
