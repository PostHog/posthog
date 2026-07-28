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
 * Recent ReviewHog reviews on this project: actively running reviews first (with the in-flight turn's stage), then the most recent completed ones — at most `limit` rows (default 5), plus `has_more` for whether a larger `limit` would reveal more. By default only the requesting user's reviews; `scope=everyone` lists every review on the project.
 * @summary List recent reviews
 */
export const ReviewHogReviewsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const reviewHogReviewsListQueryLimitDefault = 5
export const reviewHogReviewsListQueryLimitMax = 100

export const reviewHogReviewsListQueryScopeDefault = `mine`

export const ReviewHogReviewsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod
        .number()
        .min(1)
        .max(reviewHogReviewsListQueryLimitMax)
        .default(reviewHogReviewsListQueryLimitDefault)
        .describe(
            'Maximum rows to return. The list grows this instead of paging by offset — in-progress rows reorder the list between refreshes, so offset pages would shift under the reader.'
        ),
    scope: zod
        .enum(['mine', 'everyone'])
        .default(reviewHogReviewsListQueryScopeDefault)
        .describe(
            "Whose reviews to list: `mine` for reviews of the requesting user's pull requests (the default), `everyone` for every review on this project.\n\n\* `mine` - mine\n\* `everyone` - everyone"
        ),
})

/**
 * One completed ReviewHog review on this project, with the latest turn's validated findings, the findings the validator dismissed (and why), and the review body published to GitHub. Project-wide, so reviews listed under `scope=everyone` can be opened too.
 * @summary Retrieve one review's detail
 */
export const ReviewHogReviewsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this review report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Start a ReviewHog review of any pull request the project's GitHub App installation can access, and publish it back to the PR. The requesting user is the review's acting user: their enabled perspectives, blind-spot check, validator, and urgency threshold drive the run, and it appears under their recent reviews. Nonexistent, closed, and fork PRs are rejected synchronously; a PR whose current commit already has a published review returns 'already_reviewed' without starting a run, and triggering a PR whose review is currently running joins the in-flight run. Otherwise non-blocking: returns the Temporal workflow id immediately while the review runs in the worker.
 * @summary Start a review of a pull request
 */
export const ReviewHogReviewsTriggerCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ReviewHogReviewsTriggerCreateBody = /* @__PURE__ */ zod.object({
    pr_url: zod
        .string()
        .describe(
            "GitHub pull request URL to review, e.g. 'https:\/\/github.com\/PostHog\/posthog.com\/pull\/123'. The repository must be accessible to the project's GitHub App installation."
        ),
})
