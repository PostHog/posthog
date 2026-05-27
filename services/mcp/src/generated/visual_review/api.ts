/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
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
 * Approve visual changes for snapshots in this run.

With approve_all=true, approves all changed+new snapshots and returns
signed baseline YAML. With specific snapshots, approves only those.
 */
export const VisualReviewRunsApproveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const visualReviewRunsApproveCreateBodyApproveAllDefault = false
export const visualReviewRunsApproveCreateBodyCommitToGithubDefault = true

export const VisualReviewRunsApproveCreateBody = /* @__PURE__ */ zod.object({
    snapshots: zod
        .array(
            zod.object({
                identifier: zod
                    .string()
                    .describe('The snapshot identifier to approve (e.g. Storybook story id plus theme).'),
                new_hash: zod
                    .string()
                    .describe('The content hash of the new baseline image to record for this identifier.'),
            })
        )
        .optional()
        .describe(
            'Specific snapshots to approve, each with `identifier` and `new_hash`. Ignored when `approve_all` is true.'
        ),
    approve_all: zod
        .boolean()
        .default(visualReviewRunsApproveCreateBodyApproveAllDefault)
        .describe(
            'Approve every changed and new snapshot in the run. Mutually exclusive with `snapshots` — pass one or the other.'
        ),
    commit_to_github: zod
        .boolean()
        .default(visualReviewRunsApproveCreateBodyCommitToGithubDefault)
        .describe(
            'Whether to commit the updated baseline YAML to the PR branch on GitHub. Set to false to record the approval without pushing a commit.'
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
 * Mark a changed snapshot as a known tolerated alternate.
 */
export const VisualReviewRunsTolerateCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisualReviewRunsTolerateCreateBody = /* @__PURE__ */ zod.object({
    snapshot_id: zod
        .string()
        .describe(
            'UUID of the changed snapshot to mark as a known tolerated alternate. Future runs that produce the same alternate hash for this identifier will not be flagged as changes.'
        ),
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
