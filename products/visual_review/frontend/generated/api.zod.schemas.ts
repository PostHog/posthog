/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const RepoApi = zod.object({
    id: zod.uuid(),
    team_id: zod.number(),
    repo_external_id: zod.number(),
    repo_full_name: zod.string(),
    baseline_file_paths: zod.record(zod.string(), zod.string()),
    enable_pr_comments: zod.boolean(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type RepoApi = zod.input<typeof RepoApi>
export type RepoApiOutput = zod.output<typeof RepoApi>

export const PaginatedRepoListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(RepoApi),
})

export type PaginatedRepoListApi = zod.input<typeof PaginatedRepoListApi>
export type PaginatedRepoListApiOutput = zod.output<typeof PaginatedRepoListApi>

export const CreateRepoInputApi = zod.object({
    repo_full_name: zod.string(),
    repo_external_id: zod.number().nullish(),
})

export type CreateRepoInputApi = zod.input<typeof CreateRepoInputApi>
export type CreateRepoInputApiOutput = zod.output<typeof CreateRepoInputApi>

export const PatchedUpdateRepoRequestInputApi = zod.object({
    baseline_file_paths: zod.record(zod.string(), zod.string()).nullish(),
    enable_pr_comments: zod.boolean().nullish(),
})

export type PatchedUpdateRepoRequestInputApi = zod.input<typeof PatchedUpdateRepoRequestInputApi>
export type PatchedUpdateRepoRequestInputApiOutput = zod.output<typeof PatchedUpdateRepoRequestInputApi>

export const UserBasicInfoApi = zod.object({
    id: zod.number(),
    first_name: zod.string(),
    email: zod.string(),
})

export type UserBasicInfoApi = zod.input<typeof UserBasicInfoApi>
export type UserBasicInfoApiOutput = zod.output<typeof UserBasicInfoApi>

export const QuarantineSourceRunApi = zod.object({
    id: zod.uuid(),
    branch: zod.string(),
    commit_sha: zod.string(),
    created_at: zod.iso.datetime({ offset: true }),
    pr_number: zod.number().nullish(),
})

export type QuarantineSourceRunApi = zod.input<typeof QuarantineSourceRunApi>
export type QuarantineSourceRunApiOutput = zod.output<typeof QuarantineSourceRunApi>

export const BaselineQuarantineSummaryApi = zod.object({
    created_by: zod.union([UserBasicInfoApi, zod.null()]).optional(),
    source_run: zod.union([QuarantineSourceRunApi, zod.null()]).optional(),
    id: zod.uuid(),
    reason: zod.string(),
    expires_at: zod.iso.datetime({ offset: true }).nullable(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type BaselineQuarantineSummaryApi = zod.input<typeof BaselineQuarantineSummaryApi>
export type BaselineQuarantineSummaryApiOutput = zod.output<typeof BaselineQuarantineSummaryApi>

export const BaselineEntryApi = zod.object({
    quarantine: zod
        .union([BaselineQuarantineSummaryApi, zod.null()])
        .optional()
        .describe('Active quarantine details when `is_quarantined` is true. Null otherwise.'),
    identifier: zod.string(),
    run_type: zod.string(),
    browser: zod.string().nullable(),
    thumbnail_hash: zod.string().nullable(),
    width: zod.number().nullable(),
    height: zod.number().nullable(),
    tolerate_count_30d: zod.number(),
    tolerate_count_90d: zod.number(),
    is_quarantined: zod.boolean(),
    last_run_at: zod.iso.datetime({ offset: true }),
    baseline_change_count: zod.number(),
    recent_drift_avg: zod.number().nullable(),
})

export type BaselineEntryApi = zod.input<typeof BaselineEntryApi>
export type BaselineEntryApiOutput = zod.output<typeof BaselineEntryApi>

export const BaselineTotalsApi = zod.object({
    by_run_type: zod.record(zod.string(), zod.number()),
    all_snapshots: zod.number(),
    recently_tolerated: zod.number(),
    frequently_tolerated: zod.number(),
    currently_quarantined: zod.number(),
})

export type BaselineTotalsApi = zod.input<typeof BaselineTotalsApi>
export type BaselineTotalsApiOutput = zod.output<typeof BaselineTotalsApi>

export const BaselineOverviewApi = zod.object({
    entries: zod.array(BaselineEntryApi),
    totals: BaselineTotalsApi,
    truncated: zod.boolean(),
    generated_at: zod.iso.datetime({ offset: true }),
})

export type BaselineOverviewApi = zod.input<typeof BaselineOverviewApi>
export type BaselineOverviewApiOutput = zod.output<typeof BaselineOverviewApi>

export const QuarantinedIdentifierEntryApi = zod.object({
    created_by: zod.union([UserBasicInfoApi, zod.null()]).optional(),
    source_run: zod
        .union([QuarantineSourceRunApi, zod.null()])
        .optional()
        .describe(
            'Run whose failing snapshot prompted this quarantine. Null when quarantine was created without run context.'
        ),
    id: zod.uuid(),
    identifier: zod.string(),
    run_type: zod.string(),
    reason: zod.string(),
    expires_at: zod.iso.datetime({ offset: true }).nullable(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type QuarantinedIdentifierEntryApi = zod.input<typeof QuarantinedIdentifierEntryApi>
export type QuarantinedIdentifierEntryApiOutput = zod.output<typeof QuarantinedIdentifierEntryApi>

export const PaginatedQuarantinedIdentifierEntryListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(QuarantinedIdentifierEntryApi),
})

export type PaginatedQuarantinedIdentifierEntryListApi = zod.input<typeof PaginatedQuarantinedIdentifierEntryListApi>
export type PaginatedQuarantinedIdentifierEntryListApiOutput = zod.output<
    typeof PaginatedQuarantinedIdentifierEntryListApi
>

export const quarantineInputApiIdentifierMax = 512

export const quarantineInputApiReasonMax = 255

export const QuarantineInputApi = zod.object({
    identifier: zod.string().max(quarantineInputApiIdentifierMax).describe('Snapshot identifier to quarantine.'),
    reason: zod.string().max(quarantineInputApiReasonMax).describe('Why this snapshot is being quarantined.'),
    source_run_id: zod
        .uuid()
        .nullish()
        .describe(
            "Optional pointer to the run whose failing snapshot prompted this quarantine — used to surface a 'view the failing run' link later."
        ),
    expires_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type QuarantineInputApi = zod.input<typeof QuarantineInputApi>
export type QuarantineInputApiOutput = zod.output<typeof QuarantineInputApi>

export const SearchMatchTypeEnumApi = zod.enum(['exact', 'similar'])

export type SearchMatchTypeEnumApi = zod.input<typeof SearchMatchTypeEnumApi>
export type SearchMatchTypeEnumApiOutput = zod.output<typeof SearchMatchTypeEnumApi>

export const RunSummaryApi = zod.object({
    total: zod.number(),
    changed: zod.number(),
    new: zod.number(),
    removed: zod.number(),
    unchanged: zod.number(),
    unresolved: zod.number().optional(),
    tolerated_matched: zod.number().optional(),
})

export type RunSummaryApi = zod.input<typeof RunSummaryApi>
export type RunSummaryApiOutput = zod.output<typeof RunSummaryApi>

export const RunApi = zod.object({
    approved_by: zod.union([UserBasicInfoApi, zod.null()]).optional(),
    search_match_type: zod
        .union([SearchMatchTypeEnumApi, zod.null()])
        .describe(
            'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of branch\/run type, a commit SHA prefix, or an exact PR number) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.\n\n\* `exact` - exact\n\* `similar` - similar'
        ),
    id: zod.uuid(),
    repo_id: zod.uuid(),
    status: zod.string(),
    run_type: zod.string(),
    commit_sha: zod.string(),
    branch: zod.string(),
    pr_number: zod.number().nullable(),
    approved: zod.boolean(),
    approved_at: zod.iso.datetime({ offset: true }).nullable(),
    summary: RunSummaryApi,
    error_message: zod.string().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
    completed_at: zod.iso.datetime({ offset: true }).nullable(),
    is_stale: zod.boolean().optional(),
    superseded_by_id: zod.uuid().nullish(),
    metadata: zod.record(zod.string(), zod.unknown()).optional(),
})

export type RunApi = zod.input<typeof RunApi>
export type RunApiOutput = zod.output<typeof RunApi>

export const PaginatedRunListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(RunApi),
})

export type PaginatedRunListApi = zod.input<typeof PaginatedRunListApi>
export type PaginatedRunListApiOutput = zod.output<typeof PaginatedRunListApi>

export const ReviewStateCountsApi = zod.object({
    needs_review: zod.number(),
    clean: zod.number(),
    processing: zod.number(),
    stale: zod.number(),
})

export type ReviewStateCountsApi = zod.input<typeof ReviewStateCountsApi>
export type ReviewStateCountsApiOutput = zod.output<typeof ReviewStateCountsApi>

export const ArtifactApi = zod.object({
    id: zod.uuid(),
    content_hash: zod.string(),
    width: zod.number().nullable(),
    height: zod.number().nullable(),
    download_url: zod.string().nullable(),
})

export type ArtifactApi = zod.input<typeof ArtifactApi>
export type ArtifactApiOutput = zod.output<typeof ArtifactApi>

export const SnapshotHistoryEntryApi = zod.object({
    current_artifact: zod.union([ArtifactApi, zod.null()]).optional(),
    run_id: zod.uuid(),
    snapshot_id: zod.uuid(),
    result: zod.string(),
    branch: zod.string(),
    commit_sha: zod.string(),
    created_at: zod.iso.datetime({ offset: true }),
    pr_number: zod.number().nullish(),
    diff_percentage: zod.number().nullish(),
    review_state: zod.string().optional(),
    ssim_score: zod.number().nullish(),
    change_kind: zod.string().optional(),
    size_mismatch: zod.boolean().optional(),
})

export type SnapshotHistoryEntryApi = zod.input<typeof SnapshotHistoryEntryApi>
export type SnapshotHistoryEntryApiOutput = zod.output<typeof SnapshotHistoryEntryApi>

export const PaginatedSnapshotHistoryEntryListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SnapshotHistoryEntryApi),
})

export type PaginatedSnapshotHistoryEntryListApi = zod.input<typeof PaginatedSnapshotHistoryEntryListApi>
export type PaginatedSnapshotHistoryEntryListApiOutput = zod.output<typeof PaginatedSnapshotHistoryEntryListApi>

export const SnapshotManifestItemApi = zod.object({
    identifier: zod.string(),
    content_hash: zod.string(),
    width: zod.number().nullish(),
    height: zod.number().nullish(),
    metadata: zod.record(zod.string(), zod.unknown()).optional(),
})

export type SnapshotManifestItemApi = zod.input<typeof SnapshotManifestItemApi>
export type SnapshotManifestItemApiOutput = zod.output<typeof SnapshotManifestItemApi>

export const CreateRunInputApi = zod.object({
    repo_id: zod.uuid(),
    run_type: zod.string(),
    commit_sha: zod.string(),
    branch: zod.string(),
    snapshots: zod.array(SnapshotManifestItemApi),
    pr_number: zod.number().nullish(),
    baseline_hashes: zod.record(zod.string(), zod.string()).optional(),
    unchanged_count: zod.number().optional(),
    removed_identifiers: zod.array(zod.string()).optional(),
    purpose: zod.string().optional(),
    metadata: zod.record(zod.string(), zod.unknown()).optional(),
    is_partial: zod.boolean().optional(),
})

export type CreateRunInputApi = zod.input<typeof CreateRunInputApi>
export type CreateRunInputApiOutput = zod.output<typeof CreateRunInputApi>

export const UploadTargetApi = zod.object({
    content_hash: zod.string(),
    url: zod.string(),
    fields: zod.record(zod.string(), zod.string()),
})

export type UploadTargetApi = zod.input<typeof UploadTargetApi>
export type UploadTargetApiOutput = zod.output<typeof UploadTargetApi>

export const CreateRunResultApi = zod.object({
    run_id: zod.uuid(),
    uploads: zod.array(UploadTargetApi),
})

export type CreateRunResultApi = zod.input<typeof CreateRunResultApi>
export type CreateRunResultApiOutput = zod.output<typeof CreateRunResultApi>

export const AddSnapshotsInputApi = zod.object({
    snapshots: zod.array(SnapshotManifestItemApi),
    baseline_hashes: zod.record(zod.string(), zod.string()).optional(),
})

export type AddSnapshotsInputApi = zod.input<typeof AddSnapshotsInputApi>
export type AddSnapshotsInputApiOutput = zod.output<typeof AddSnapshotsInputApi>

export const AddSnapshotsResultApi = zod.object({
    added: zod.number(),
    uploads: zod.array(UploadTargetApi),
})

export type AddSnapshotsResultApi = zod.input<typeof AddSnapshotsResultApi>
export type AddSnapshotsResultApiOutput = zod.output<typeof AddSnapshotsResultApi>

export const ApproveSnapshotInputApi = zod.object({
    identifier: zod.string().describe('The snapshot identifier to approve (e.g. Storybook story id plus theme).'),
    new_hash: zod.string().describe('The content hash of the new baseline image to record for this identifier.'),
})

export type ApproveSnapshotInputApi = zod.input<typeof ApproveSnapshotInputApi>
export type ApproveSnapshotInputApiOutput = zod.output<typeof ApproveSnapshotInputApi>

export const ApproveRunRequestInputApi = zod.object({
    snapshots: zod
        .array(ApproveSnapshotInputApi)
        .describe(
            'Snapshots to mark reviewed, each with `identifier` and `new_hash`. This only records the review in the database (the per-snapshot \"Accept change\" action) — it does not change the baseline or the GitHub gate. Commit the baseline and green the gate with the finalize endpoint.'
        ),
})

export type ApproveRunRequestInputApi = zod.input<typeof ApproveRunRequestInputApi>
export type ApproveRunRequestInputApiOutput = zod.output<typeof ApproveRunRequestInputApi>

export const finalizeRunRequestInputApiApproveAllDefault = false
export const finalizeRunRequestInputApiCommitToGithubDefault = true
export const finalizeRunRequestInputApiAddImagesToCommentOnPrDefault = false

export const FinalizeRunRequestInputApi = zod.object({
    approve_all: zod
        .boolean()
        .default(finalizeRunRequestInputApiApproveAllDefault)
        .describe(
            "Approve every still-pending changed and new snapshot before finalizing (tolerated snapshots are left untouched). Leave false to finalize a run you've already reviewed — finalizing fails if any changed\/new snapshot is still unreviewed."
        ),
    commit_to_github: zod
        .boolean()
        .default(finalizeRunRequestInputApiCommitToGithubDefault)
        .describe(
            'Whether the server commits the approved baseline to the PR branch and greens the gate (the normal path — leave true). Set false only for tooling that commits the baseline itself: the server skips the commit and returns the signed YAML in `baseline_content` instead. With false, the gate is NOT greened and `metadata.baseline_commit_sha` is absent.'
        ),
    add_images_to_comment_on_pr: zod
        .boolean()
        .default(finalizeRunRequestInputApiAddImagesToCommentOnPrDefault)
        .describe(
            'Whether to embed the before\/after snapshot images in the post-approval PR comment. The comment itself is always posted (when the run was initiated from a GitHub review prompt and the repo has PR comments enabled); this flag only controls the images. Defaults false — the comment stays a text summary unless the reviewer opts in to attach the snapshots.'
        ),
})

export type FinalizeRunRequestInputApi = zod.input<typeof FinalizeRunRequestInputApi>
export type FinalizeRunRequestInputApiOutput = zod.output<typeof FinalizeRunRequestInputApi>

export const FinalizeResultApi = zod.object({
    run: RunApi,
    baseline_content: zod.string(),
})

export type FinalizeResultApi = zod.input<typeof FinalizeResultApi>
export type FinalizeResultApiOutput = zod.output<typeof FinalizeResultApi>

export const RecomputeResultApi = zod.object({
    run: RunApi,
    counts_changed: zod.boolean(),
    unresolved: zod.number(),
    ci_rerun_triggered: zod.boolean(),
    ci_rerun_error: zod.string().nullish(),
})

export type RecomputeResultApi = zod.input<typeof RecomputeResultApi>
export type RecomputeResultApiOutput = zod.output<typeof RecomputeResultApi>

export const DiffClusterApi = zod.object({
    x: zod.number(),
    y: zod.number(),
    width: zod.number(),
    height: zod.number(),
    pixel_count: zod.number(),
    centroid_x: zod.number(),
    centroid_y: zod.number(),
})

export type DiffClusterApi = zod.input<typeof DiffClusterApi>
export type DiffClusterApiOutput = zod.output<typeof DiffClusterApi>

export const ClusterSummaryApi = zod.object({
    items: zod.array(DiffClusterApi),
    total: zod.number(),
    truncated: zod.boolean(),
})

export type ClusterSummaryApi = zod.input<typeof ClusterSummaryApi>
export type ClusterSummaryApiOutput = zod.output<typeof ClusterSummaryApi>

export const SnapshotApi = zod.object({
    current_artifact: zod.union([ArtifactApi, zod.null()]).optional(),
    baseline_artifact: zod.union([ArtifactApi, zod.null()]).optional(),
    diff_artifact: zod.union([ArtifactApi, zod.null()]).optional(),
    reviewed_by: zod.union([UserBasicInfoApi, zod.null()]).optional(),
    cluster_summary: zod.union([ClusterSummaryApi, zod.null()]).optional(),
    id: zod.uuid(),
    run_id: zod.uuid(),
    identifier: zod.string(),
    result: zod.string(),
    classification_reason: zod.string(),
    diff_percentage: zod.number().nullable(),
    diff_pixel_count: zod.number().nullable(),
    review_state: zod.string(),
    reviewed_at: zod.iso.datetime({ offset: true }).nullable(),
    approved_hash: zod.string(),
    tolerated_hash_id: zod.uuid().nullish(),
    is_quarantined: zod.boolean().optional(),
    metadata: zod.record(zod.string(), zod.unknown()).optional(),
    ssim_score: zod.number().nullish(),
    change_kind: zod.string().optional(),
    size_mismatch: zod.boolean().optional(),
})

export type SnapshotApi = zod.input<typeof SnapshotApi>
export type SnapshotApiOutput = zod.output<typeof SnapshotApi>

export const PaginatedSnapshotListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SnapshotApi),
    quarantined_count: zod
        .number()
        .optional()
        .describe(
            "Count of this run's snapshots whose identifier is currently quarantined. Excluded from results unless include_quarantined=true is passed."
        ),
})

export type PaginatedSnapshotListApi = zod.input<typeof PaginatedSnapshotListApi>
export type PaginatedSnapshotListApiOutput = zod.output<typeof PaginatedSnapshotListApi>

export const MarkToleratedInputApi = zod.object({
    snapshot_id: zod
        .uuid()
        .describe(
            'UUID of the changed snapshot to mark as a known tolerated alternate. Future runs that produce the same alternate hash for this identifier will not be flagged as changes.'
        ),
})

export type MarkToleratedInputApi = zod.input<typeof MarkToleratedInputApi>
export type MarkToleratedInputApiOutput = zod.output<typeof MarkToleratedInputApi>

export const ToleratedHashEntryApi = zod.object({
    id: zod.uuid(),
    alternate_hash: zod.string(),
    baseline_hash: zod.string(),
    reason: zod.string(),
    diff_percentage: zod.number().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
    source_run_id: zod.uuid().nullable(),
})

export type ToleratedHashEntryApi = zod.input<typeof ToleratedHashEntryApi>
export type ToleratedHashEntryApiOutput = zod.output<typeof ToleratedHashEntryApi>

export const PaginatedToleratedHashEntryListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ToleratedHashEntryApi),
})

export type PaginatedToleratedHashEntryListApi = zod.input<typeof PaginatedToleratedHashEntryListApi>
export type PaginatedToleratedHashEntryListApiOutput = zod.output<typeof PaginatedToleratedHashEntryListApi>
