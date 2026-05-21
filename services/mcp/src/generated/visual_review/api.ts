/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List all projects for the team.
 */
export const VisualReviewReposListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisualReviewReposListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Get a repo by ID.
 */
export const VisualReviewReposRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List runs for the team, optionally filtered by review state, PR number, commit SHA, or branch.
 */
export const VisualReviewRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisualReviewRunsListQueryParams = /* @__PURE__ */ zod.object({
    branch: zod.string().optional().describe('Filter by branch name'),
    commit_sha: zod.string().optional().describe('Filter by full commit SHA'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    pr_number: zod.number().optional().describe('Filter by GitHub PR number'),
    review_state: zod.string().optional().describe('Filter by review state'),
})

/**
 * Get run status and summary.
 */
export const VisualReviewRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Recent change history for a snapshot identifier across runs.
 */
export const VisualReviewRunsSnapshotHistoryListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisualReviewRunsSnapshotHistoryListQueryParams = /* @__PURE__ */ zod.object({
    identifier: zod.string().describe('Snapshot identifier'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Get all snapshots for a run with diff results.
 */
export const VisualReviewRunsSnapshotsListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisualReviewRunsSnapshotsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * List known tolerated hashes for a snapshot identifier.
 */
export const VisualReviewRunsToleratedHashesListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisualReviewRunsToleratedHashesListQueryParams = /* @__PURE__ */ zod.object({
    identifier: zod.string().describe('Snapshot identifier'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Review state counts for the runs list.
 */
export const VisualReviewRunsCountsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
