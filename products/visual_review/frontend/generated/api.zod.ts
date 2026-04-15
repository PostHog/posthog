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
 * List all projects for the team.
 */
export const VisualReviewReposListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            team_id: zod.number(),
            repo_external_id: zod.number(),
            repo_full_name: zod.string(),
            baseline_file_paths: zod.record(zod.string(), zod.string()),
            enable_pr_comments: zod.boolean(),
            created_at: zod.iso.datetime({}),
        })
    ),
})

/**
 * Create a new repo.
 */
export const VisualReviewReposCreateBody = /* @__PURE__ */ zod.object({
    repo_full_name: zod.string(),
    repo_external_id: zod.number().nullish(),
})

/**
 * Get a repo by ID.
 */
export const VisualReviewReposRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    team_id: zod.number(),
    repo_external_id: zod.number(),
    repo_full_name: zod.string(),
    baseline_file_paths: zod.record(zod.string(), zod.string()),
    enable_pr_comments: zod.boolean(),
    created_at: zod.iso.datetime({}),
})

/**
 * Update a repo's settings.
 */
export const VisualReviewReposPartialUpdateBody = /* @__PURE__ */ zod.object({
    baseline_file_paths: zod.record(zod.string(), zod.string()).nullish(),
    enable_pr_comments: zod.boolean().nullish(),
})

export const VisualReviewReposPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    team_id: zod.number(),
    repo_external_id: zod.number(),
    repo_full_name: zod.string(),
    baseline_file_paths: zod.record(zod.string(), zod.string()),
    enable_pr_comments: zod.boolean(),
    created_at: zod.iso.datetime({}),
})

/**
 * List runs for the team, optionally filtered by review state.
 */
export const VisualReviewRunsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
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
            }),
            error_message: zod.string().nullable(),
            created_at: zod.iso.datetime({}),
            completed_at: zod.iso.datetime({}).nullable(),
            is_stale: zod.boolean().optional(),
            metadata: zod.record(zod.string(), zod.unknown()).optional(),
        })
    ),
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
 * Get run status and summary.
 */
export const VisualReviewRunsRetrieveResponse = /* @__PURE__ */ zod.object({
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
    }),
    error_message: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    completed_at: zod.iso.datetime({}).nullable(),
    is_stale: zod.boolean().optional(),
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

export const VisualReviewRunsAddSnapshotsCreateResponse = /* @__PURE__ */ zod.object({
    added: zod.number(),
    uploads: zod.array(
        zod.object({
            content_hash: zod.string(),
            url: zod.string(),
            fields: zod.record(zod.string(), zod.string()),
        })
    ),
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

export const VisualReviewRunsApproveCreateResponse = /* @__PURE__ */ zod.object({
    run: zod.object({
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
        }),
        error_message: zod.string().nullable(),
        created_at: zod.iso.datetime({}),
        completed_at: zod.iso.datetime({}).nullable(),
        is_stale: zod.boolean().optional(),
        metadata: zod.record(zod.string(), zod.unknown()).optional(),
    }),
    baseline_content: zod.string(),
})

/**
 * Complete a run: detect removals, verify uploads, trigger diff processing.
 */
export const VisualReviewRunsCompleteCreateResponse = /* @__PURE__ */ zod.object({
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
    }),
    error_message: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    completed_at: zod.iso.datetime({}).nullable(),
    is_stale: zod.boolean().optional(),
    metadata: zod.record(zod.string(), zod.unknown()).optional(),
})

/**
 * Recent change history for a snapshot identifier across runs.
 */
export const VisualReviewRunsSnapshotHistoryListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            run_id: zod.uuid(),
            result: zod.string(),
            branch: zod.string(),
            commit_sha: zod.string(),
            created_at: zod.iso.datetime({}),
        })
    ),
})

/**
 * Get all snapshots for a run with diff results.
 */
export const VisualReviewRunsSnapshotsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            current_artifact: zod
                .object({
                    id: zod.uuid(),
                    content_hash: zod.string(),
                    width: zod.number().nullable(),
                    height: zod.number().nullable(),
                    download_url: zod.string().nullable(),
                })
                .nullish(),
            baseline_artifact: zod
                .object({
                    id: zod.uuid(),
                    content_hash: zod.string(),
                    width: zod.number().nullable(),
                    height: zod.number().nullable(),
                    download_url: zod.string().nullable(),
                })
                .nullish(),
            diff_artifact: zod
                .object({
                    id: zod.uuid(),
                    content_hash: zod.string(),
                    width: zod.number().nullable(),
                    height: zod.number().nullable(),
                    download_url: zod.string().nullable(),
                })
                .nullish(),
            id: zod.uuid(),
            identifier: zod.string(),
            result: zod.string(),
            diff_percentage: zod.number().nullable(),
            diff_pixel_count: zod.number().nullable(),
            review_state: zod.string(),
            reviewed_at: zod.iso.datetime({}).nullable(),
            approved_hash: zod.string(),
            metadata: zod.record(zod.string(), zod.unknown()).optional(),
        })
    ),
})

/**
 * Review state counts for the runs list.
 */
export const VisualReviewRunsCountsRetrieveResponse = /* @__PURE__ */ zod.object({
    needs_review: zod.number(),
    clean: zod.number(),
    processing: zod.number(),
    stale: zod.number(),
})
