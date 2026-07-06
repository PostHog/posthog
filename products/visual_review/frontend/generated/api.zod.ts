/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create a new repo.
 */
export const VisualReviewReposCreateBody = /* @__PURE__ */ zod.object({
    repo_full_name: zod.string(),
    repo_external_id: zod.number().nullish(),
})

/**
 * Update a repo's settings.
 */
export const VisualReviewReposPartialUpdateBody = /* @__PURE__ */ zod.object({
    baseline_file_paths: zod.record(zod.string(), zod.string()).nullish(),
    enable_pr_comments: zod.boolean().nullish(),
})

/**
 * Quarantine a snapshot identifier for a specific run type.
 */
export const visualReviewReposQuarantineCreateBodyIdentifierMax = 512

export const visualReviewReposQuarantineCreateBodyReasonMax = 255

export const VisualReviewReposQuarantineCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(visualReviewReposQuarantineCreateBodyIdentifierMax)
        .describe('Snapshot identifier to quarantine.'),
    reason: zod
        .string()
        .max(visualReviewReposQuarantineCreateBodyReasonMax)
        .describe('Why this snapshot is being quarantined.'),
    source_run_id: zod
        .uuid()
        .nullish()
        .describe(
            "Optional pointer to the run whose failing snapshot prompted this quarantine — used to surface a 'view the failing run' link later."
        ),
    expires_at: zod.iso.datetime({ offset: true }).nullish(),
})

/**
 * Expire all active quarantine entries for an identifier.
 */
export const visualReviewReposQuarantineExpireCreateBodyIdentifierMax = 512

export const visualReviewReposQuarantineExpireCreateBodyReasonMax = 255

export const VisualReviewReposQuarantineExpireCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(visualReviewReposQuarantineExpireCreateBodyIdentifierMax)
        .describe('Snapshot identifier to quarantine.'),
    reason: zod
        .string()
        .max(visualReviewReposQuarantineExpireCreateBodyReasonMax)
        .describe('Why this snapshot is being quarantined.'),
    source_run_id: zod
        .uuid()
        .nullish()
        .describe(
            "Optional pointer to the run whose failing snapshot prompted this quarantine — used to surface a 'view the failing run' link later."
        ),
    expires_at: zod.iso.datetime({ offset: true }).nullish(),
})

/**
 * Create a new run from a CI manifest.
 */
export const VisualReviewRunsCreateBody = /* @__PURE__ */ zod.object({
    repo_id: zod.uuid(),
    run_type: zod.string(),
    commit_sha: zod.string(),
    branch: zod.string(),
    snapshots: zod.array(
        zod.object({
            identifier: zod.string(),
            content_hash: zod.string(),
            width: zod.number().nullish(),
            height: zod.number().nullish(),
            metadata: zod.record(zod.string(), zod.unknown()).optional(),
        })
    ),
    pr_number: zod.number().nullish(),
    baseline_hashes: zod.record(zod.string(), zod.string()).optional(),
    unchanged_count: zod.number().optional(),
    removed_identifiers: zod.array(zod.string()).optional(),
    purpose: zod.string().optional(),
    metadata: zod.record(zod.string(), zod.unknown()).optional(),
    is_partial: zod.boolean().optional(),
})

/**
 * Add a batch of snapshots to a pending run (shard-based flow).
 */
export const VisualReviewRunsAddSnapshotsCreateBody = /* @__PURE__ */ zod.object({
    snapshots: zod.array(
        zod.object({
            identifier: zod.string(),
            content_hash: zod.string(),
            width: zod.number().nullish(),
            height: zod.number().nullish(),
            metadata: zod.record(zod.string(), zod.unknown()).optional(),
        })
    ),
    baseline_hashes: zod.record(zod.string(), zod.string()).optional(),
})

/**
 * Mark snapshots reviewed (DB only).
 *
 * Records the per-snapshot "Accept change" decision. Does not commit the baseline
 * or change the GitHub gate — call finalize to ship the run.
 */
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
 * any still-pending changed/new snapshot is approved first. With commit_to_github=false
 * the server returns the signed baseline YAML instead of committing it.
 */
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
 * Mark a changed snapshot as a known tolerated alternate.
 */
export const VisualReviewRunsTolerateCreateBody = /* @__PURE__ */ zod.object({
    snapshot_id: zod
        .uuid()
        .describe(
            'UUID of the changed snapshot to mark as a known tolerated alternate. Future runs that produce the same alternate hash for this identifier will not be flagged as changes.'
        ),
})
