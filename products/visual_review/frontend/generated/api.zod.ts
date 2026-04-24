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
    identifier: zod.string().max(visualReviewReposQuarantineCreateBodyIdentifierMax),
    reason: zod.string().max(visualReviewReposQuarantineCreateBodyReasonMax),
    expires_at: zod.iso.datetime({}).nullish(),
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
 * Approve visual changes for snapshots in this run.

With approve_all=true, approves all changed+new snapshots and returns
signed baseline YAML. With specific snapshots, approves only those.
 */
export const VisualReviewRunsApproveCreateBody = /* @__PURE__ */ zod.object({
    snapshots: zod
        .array(
            zod.object({
                identifier: zod.string(),
                new_hash: zod.string(),
            })
        )
        .optional(),
    approve_all: zod.boolean().optional(),
    commit_to_github: zod.boolean().optional(),
})

/**
 * Complete a run: detect removals, verify uploads, trigger diff processing.
 */
export const VisualReviewRunsCompleteCreateBody = /* @__PURE__ */ zod.object({
    approved_by: zod
        .object({
            id: zod.number(),
            first_name: zod.string(),
            email: zod.string(),
        })
        .nullish(),
    id: zod.uuid(),
    repo_id: zod.uuid(),
    status: zod.string(),
    run_type: zod.string(),
    commit_sha: zod.string(),
    branch: zod.string(),
    pr_number: zod.number().nullable(),
    approved: zod.boolean(),
    approved_at: zod.iso.datetime({}).nullable(),
    summary: zod.object({
        total: zod.number(),
        changed: zod.number(),
        new: zod.number(),
        removed: zod.number(),
        unchanged: zod.number(),
        tolerated_matched: zod.number().optional(),
    }),
    error_message: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    completed_at: zod.iso.datetime({}).nullable(),
    is_stale: zod.boolean().optional(),
    superseded_by_id: zod.uuid().nullish(),
    metadata: zod.record(zod.string(), zod.unknown()).optional(),
})

/**
 * Mark a changed snapshot as a known tolerated alternate.
 */
export const VisualReviewRunsTolerateCreateBody = /* @__PURE__ */ zod.object({
    snapshot_id: zod.uuid(),
})
