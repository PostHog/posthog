/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 15 enabled ops
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Snapshots in a repo whose rendering cannot be trusted: those that failed the gate or were absorbed by a toleration on a recent default-branch run, and those under an active quarantine. Everything else is omitted, so this is far smaller than the baselines universe; `totals.tracked` gives the full denominator. Each entry carries the share of the last 7 days of default-branch runs that failed the gate (`hard_rate`) and the share a toleration absorbed (`soft_rate`), plus `headroom`, the fraction of the diff threshold its worst absorbed run leaves free. Capped at 2000 entries, which sets `truncated`. Filtering, faceting and search are done client-side; this endpoint takes no filter query params.
 */
export const VisualReviewReposFlakinessRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * List quarantined identifiers. Without filter: active only. With identifier: full history.
 */
export const VisualReviewReposQuarantineListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewReposQuarantineListQueryParams = /* @__PURE__ */ zod.object({
    identifier: zod.string().optional().describe('Filter by identifier (returns full history)'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    run_type: zod.string().optional().describe('Filter by run type'),
})

/**
 * List runs in this repo, optionally filtered by review state and free-text search.
 */
export const VisualReviewReposRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    repo_id: zod.string(),
})

export const VisualReviewReposRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    review_state: zod.string().optional().describe('Filter by review state'),
    search: zod.string().optional().describe('Free-text search over branch, commit SHA, run type, and PR number'),
})

/**
 * Review state counts for runs in this repo.
 */
export const VisualReviewReposRunsCountsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    repo_id: zod.string(),
})

/**
 * List runs for the team, optionally filtered by review state, PR number, commit SHA, branch, or free-text search.
 */
export const VisualReviewRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewRunsListQueryParams = /* @__PURE__ */ zod.object({
    branch: zod.string().optional().describe('Filter by branch name'),
    commit_sha: zod.string().optional().describe('Filter by full commit SHA'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    pr_number: zod.number().optional().describe('Filter by GitHub PR number'),
    review_state: zod.string().optional().describe('Filter by review state'),
    search: zod.string().optional().describe('Free-text search over branch, commit SHA, run type, and PR number'),
})

/**
 * Get run status and summary.
 */
export const VisualReviewRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Mark snapshots reviewed (DB only).
 *
 * Records the per-snapshot "Accept change" decision. Does not commit the baseline
 * or change the GitHub gate — call finalize to ship the run. Works on a quarantined
 * snapshot too: a quarantined NEW snapshot approved here is committed by finalize,
 * which gives a quarantined story a baseline entry without lifting the quarantine.
 */
export const VisualReviewRunsApproveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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
        .describe(
            'Snapshots to mark reviewed, each with `identifier` and `new_hash`. This only records the review in the database (the per-snapshot \"Accept change\" action) — it does not change the baseline or the GitHub gate. Commit the baseline and green the gate with the finalize endpoint.'
        ),
})

/**
 * Finalize a fully-reviewed run: commit the approved baseline and green the gate.
 *
 * Commits exactly the snapshots approved in the DB (tolerated ones keep their baseline)
 * and only succeeds once every changed/new snapshot is resolved. With approve_all=true,
 * any still-pending changed/new snapshot is approved first; quarantined snapshots are
 * skipped, but a quarantined NEW snapshot approved by identifier is still committed.
 * With commit_to_github=false the server returns the signed baseline YAML instead of
 * committing it.
 */
export const VisualReviewRunsFinalizeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visualReviewRunsFinalizeCreateBodyApproveAllDefault = false
export const visualReviewRunsFinalizeCreateBodyCommitToGithubDefault = true
export const visualReviewRunsFinalizeCreateBodyAddImagesToCommentOnPrDefault = false

export const VisualReviewRunsFinalizeCreateBody = /* @__PURE__ */ zod.object({
    approve_all: zod
        .boolean()
        .default(visualReviewRunsFinalizeCreateBodyApproveAllDefault)
        .describe(
            "Approve every still-pending changed and new snapshot before finalizing (tolerated snapshots are left untouched). Leave false to finalize a run you've already reviewed — finalizing fails if any changed\/new snapshot is still unreviewed."
        ),
    commit_to_github: zod
        .boolean()
        .default(visualReviewRunsFinalizeCreateBodyCommitToGithubDefault)
        .describe(
            'Whether the server commits the approved baseline to the PR branch and greens the gate (the normal path — leave true). Set false only for tooling that commits the baseline itself: the server skips the commit and returns the signed YAML in `baseline_content` instead. With false, the gate is NOT greened and `metadata.baseline_commit_sha` is absent.'
        ),
    add_images_to_comment_on_pr: zod
        .boolean()
        .default(visualReviewRunsFinalizeCreateBodyAddImagesToCommentOnPrDefault)
        .describe(
            'Whether to embed the before\/after snapshot images in the post-approval PR comment. The comment itself is always posted (when the run was initiated from a GitHub review prompt and the repo has PR comments enabled); this flag only controls the images. Defaults false — the comment stays a text summary unless the reviewer opts in to attach the snapshots.'
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewRunsSnapshotHistoryListQueryParams = /* @__PURE__ */ zod.object({
    identifier: zod.string().describe('Snapshot identifier'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Get a run's snapshots with diff results, excluding quarantined ones by default.
 */
export const VisualReviewRunsSnapshotsListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewRunsSnapshotsListQueryParams = /* @__PURE__ */ zod.object({
    include_quarantined: zod
        .boolean()
        .optional()
        .describe(
            'Whether to include snapshots whose identifier is currently quarantined. Defaults to false: quarantined snapshots are excluded from results and reported in quarantined_count instead, since they are noise when reviewing real changes.'
        ),
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
