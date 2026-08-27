/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type RepoApiBaselineFilePaths = { [key: string]: string }

export interface RepoApi {
    id: string
    team_id: number
    repo_external_id: number
    repo_full_name: string
    baseline_file_paths: RepoApiBaselineFilePaths
    enable_pr_comments: boolean
    created_at: string
}

export interface PaginatedRepoListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RepoApi[]
}

export interface CreateRepoInputApi {
    repo_full_name: string
    /** @nullable */
    repo_external_id?: number | null
}

/**
 * @nullable
 */
export type PatchedUpdateRepoRequestInputApiBaselineFilePaths = { [key: string]: string } | null

export interface PatchedUpdateRepoRequestInputApi {
    /** @nullable */
    baseline_file_paths?: PatchedUpdateRepoRequestInputApiBaselineFilePaths
    /** @nullable */
    enable_pr_comments?: boolean | null
}

export interface UserBasicInfoApi {
    id: number
    first_name: string
    email: string
}

export interface QuarantineSourceRunApi {
    id: string
    branch: string
    commit_sha: string
    created_at: string
    /** @nullable */
    pr_number?: number | null
}

export interface BaselineQuarantineSummaryApi {
    created_by?: UserBasicInfoApi | null
    source_run?: QuarantineSourceRunApi | null
    id: string
    reason: string
    /** @nullable */
    expires_at: string | null
    created_at: string
}

export interface BaselineEntryApi {
    /** Active quarantine details when `is_quarantined` is true. Null otherwise. */
    quarantine?: BaselineQuarantineSummaryApi | null
    identifier: string
    run_type: string
    /** @nullable */
    browser: string | null
    /** @nullable */
    thumbnail_hash: string | null
    /** @nullable */
    width: number | null
    /** @nullable */
    height: number | null
    tolerate_count_30d: number
    tolerate_count_90d: number
    is_quarantined: boolean
    last_run_at: string
    baseline_change_count: number
    /** @nullable */
    recent_drift_avg: number | null
}

export type BaselineTotalsApiByRunType = { [key: string]: number }

export interface BaselineTotalsApi {
    by_run_type: BaselineTotalsApiByRunType
    all_snapshots: number
    recently_tolerated: number
    frequently_tolerated: number
    currently_quarantined: number
}

export interface BaselineOverviewApi {
    entries: BaselineEntryApi[]
    totals: BaselineTotalsApi
    truncated: boolean
    generated_at: string
}

/**
 * * `broken` - broken
 * * `unstable` - unstable
 * * `at_risk` - at_risk
 * * `noisy` - noisy
 * * `clean` - clean
 */
export type FlakinessStateEnumApi = (typeof FlakinessStateEnumApi)[keyof typeof FlakinessStateEnumApi]

export const FlakinessStateEnumApi = {
    Broken: 'broken',
    Unstable: 'unstable',
    AtRisk: 'at_risk',
    Noisy: 'noisy',
    Clean: 'clean',
} as const

export interface FlakinessEntryApi {
    /** Distinct alternate hashes the classifier can still match for this snapshot's current baseline. Reads as how many different images this snapshot is currently allowed to produce. Resets when the baseline moves, because tolerations recorded against an old baseline hash can never match again. */
    variant_count: number
    /** Default-branch runs in the last 7 days where this snapshot failed the gate, so somebody could not merge until it was resolved. Counts every result that is not `unchanged`: a diff over a threshold, a baseline that was never committed or was dropped, and a baseline whose story no longer renders. */
    hard_count: number
    /** Default-branch runs in the last 7 days where this snapshot rendered differently from its baseline and a toleration absorbed it, blocking nobody. */
    soft_count: number
    /** Completed default-branch runs of this run type in the last 7 days. The rate denominator, so a reader can tell 2 failures out of 3 runs from 2 out of 300. */
    window_runs: number
    /** `hard_count` over `window_runs`. The denominator counts every run of this run type, so a snapshot that only started rendering partway through the window reads lower than it is. */
    hard_rate: number
    /** `soft_count` over `window_runs`. */
    soft_rate: number
    /**
     * Last default-branch run in the last 30 days that rendered this snapshot differently from its baseline, whether the gate failed or a toleration absorbed it. Reads over the full window rather than the rate span, so a snapshot that stopped failing still reports when it last did. Null when nothing happened at all.
     * @nullable
     */
    last_flaked_at?: string | null
    /**
     * Mean fraction of pixels that differed across the live variants. Separates sub-pixel noise from a small but real rendering change.
     * @nullable
     */
    avg_diff_percentage?: number | null
    /**
     * Largest pixel diff any absorbed run in the last 30 days produced. Reads the full window rather than the rate span, because it asks for the worst case a snapshot can produce and more days are better evidence of that. Null when nothing was absorbed.
     * @nullable
     */
    worst_soft_diff_percentage?: number | null
    /**
     * Fraction of the 2.5% pixel threshold that `worst_soft_diff_percentage` leaves free. A snapshot is absorbed only while it stays under the threshold, so this is what says whether it will keep doing so: 1.0 means it rendered identically every time it was absorbed, 0.0 means it reached the line and only luck kept it on the passing side. Null when nothing was absorbed, which is not the same as full headroom.
     * @nullable
     */
    headroom?: number | null
    /**
     * Days since the first default-branch run that compared against the current baseline, which is when that baseline took effect. Reads too new for a `broken` snapshot, which records a change against an unmoved baseline on every run.
     * @nullable
     */
    baseline_age_days?: number | null
    /** Gate-failing runs per day over the last 30 days, oldest first. Always that length, so a fixed time axis can be rendered. */
    daily_hard_counts: number[]
    /** Absorbed runs per day over the same 30 days, oldest first. */
    daily_soft_counts: number[]
    /**
     * Index into the daily series where the baseline moved. Null when it moved before the window opened, which is the common case.
     * @nullable
     */
    baseline_moved_day_index?: number | null
    /** An urgency ladder, where each rung asks for a different fix. `broken` fails nearly every run, so its baseline is wrong and quarantining it only hides that. `unstable` fails some runs and not others, the classic flake. `at_risk` never fails, but its worst absorbed diff is already touching the threshold, so the next unrelated change turns it red. `noisy` renders variants and absorbs them with room to spare. `clean` matched its baseline on every run in the window.
     *
     * * `broken` - broken
     * * `unstable` - unstable
     * * `at_risk` - at_risk
     * * `noisy` - noisy
     * * `clean` - clean */
    flakiness_state: FlakinessStateEnumApi
    /** True when an active quarantine has run out, is about to, or covers a snapshot that has stopped failing the gate. All three mean a human has to extend it or lift it. */
    needs_decision: boolean
    /** Active quarantine details when `is_quarantined` is true. Null otherwise. */
    quarantine?: BaselineQuarantineSummaryApi | null
    identifier: string
    run_type: string
    /** @nullable */
    browser: string | null
    /** @nullable */
    thumbnail_hash: string | null
    /** @nullable */
    width: number | null
    /** @nullable */
    height: number | null
    is_quarantined: boolean
}

/**
 * Listed identifiers per run type, so one suite's noise can be told from another's.
 */
export type FlakinessTotalsApiByRunType = { [key: string]: number }

export interface FlakinessTotalsApi {
    /** Identifiers with an entry in `entries`. */
    listed: number
    /** Identifiers with a current baseline, listed or not. The denominator that says how much of the repo renders consistently. */
    tracked: number
    /** Identifiers whose `flakiness_state` is `broken`. */
    broken: number
    /** Identifiers whose `flakiness_state` is `unstable`. */
    unstable: number
    /** Identifiers whose `flakiness_state` is `at_risk`. */
    at_risk: number
    /** Identifiers whose `flakiness_state` is `noisy`. */
    noisy: number
    /** Identifiers whose `flakiness_state` is `clean`. They are listed because they carry live variants or older history, and reported here so every listed entry is reachable. */
    clean: number
    /** Listed identifiers per run type, so one suite's noise can be told from another's. */
    by_run_type: FlakinessTotalsApiByRunType
    quarantined: number
    needs_decision: number
}

export interface FlakinessOverviewApi {
    entries: FlakinessEntryApi[]
    totals: FlakinessTotalsApi
    truncated: boolean
    generated_at: string
}

export interface QuarantinedIdentifierEntryApi {
    created_by?: UserBasicInfoApi | null
    /** Run whose failing snapshot prompted this quarantine. Null when quarantine was created without run context. */
    source_run?: QuarantineSourceRunApi | null
    id: string
    identifier: string
    run_type: string
    reason: string
    /** @nullable */
    expires_at: string | null
    created_at: string
    updated_at: string
}

export interface PaginatedQuarantinedIdentifierEntryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: QuarantinedIdentifierEntryApi[]
}

export interface QuarantineInputApi {
    /**
     * Snapshot identifier to quarantine.
     * @maxLength 512
     */
    identifier: string
    /**
     * Why this snapshot is being quarantined.
     * @maxLength 255
     */
    reason: string
    /**
     * Optional pointer to the run whose failing snapshot prompted this quarantine — used to surface a 'view the failing run' link later.
     * @nullable
     */
    source_run_id?: string | null
    /** @nullable */
    expires_at?: string | null
}

export type SearchMatchTypeEnumApi = (typeof SearchMatchTypeEnumApi)[keyof typeof SearchMatchTypeEnumApi]

export const SearchMatchTypeEnumApi = {
    Exact: 'exact',
    Similar: 'similar',
} as const

export interface RunSummaryApi {
    total: number
    changed: number
    new: number
    removed: number
    unchanged: number
    unresolved?: number
    tolerated_matched?: number
}

export type RunApiMetadata = { [key: string]: unknown }

export interface RunApi {
    approved_by?: UserBasicInfoApi | null
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of branch/run type, a commit SHA prefix, or an exact PR number) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.
     *
     * * `exact` - exact
     * * `similar` - similar */
    readonly search_match_type: SearchMatchTypeEnumApi | null
    id: string
    repo_id: string
    status: string
    run_type: string
    commit_sha: string
    branch: string
    /** @nullable */
    pr_number: number | null
    approved: boolean
    /** @nullable */
    approved_at: string | null
    summary: RunSummaryApi
    /** @nullable */
    error_message: string | null
    created_at: string
    /** @nullable */
    completed_at: string | null
    is_stale?: boolean
    /** @nullable */
    superseded_by_id?: string | null
    metadata?: RunApiMetadata
}

export interface PaginatedRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RunApi[]
}

export interface ReviewStateCountsApi {
    needs_review: number
    clean: number
    processing: number
    stale: number
}

export interface ArtifactApi {
    id: string
    content_hash: string
    /** @nullable */
    width: number | null
    /** @nullable */
    height: number | null
    /** @nullable */
    download_url: string | null
}

export interface SnapshotHistoryEntryApi {
    current_artifact?: ArtifactApi | null
    run_id: string
    snapshot_id: string
    result: string
    branch: string
    commit_sha: string
    created_at: string
    /** @nullable */
    pr_number?: number | null
    /** @nullable */
    diff_percentage?: number | null
    review_state?: string
    /** @nullable */
    ssim_score?: number | null
    change_kind?: string
    size_mismatch?: boolean
}

export interface PaginatedSnapshotHistoryEntryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SnapshotHistoryEntryApi[]
}

export type CreateRunInputApiBaselineHashes = { [key: string]: string }

export type CreateRunInputApiMetadata = { [key: string]: unknown }

export type SnapshotManifestItemApiMetadata = { [key: string]: unknown }

export interface SnapshotManifestItemApi {
    identifier: string
    content_hash: string
    /** @nullable */
    width?: number | null
    /** @nullable */
    height?: number | null
    metadata?: SnapshotManifestItemApiMetadata
}

export interface CreateRunInputApi {
    repo_id: string
    run_type: string
    commit_sha: string
    branch: string
    snapshots: SnapshotManifestItemApi[]
    /** @nullable */
    pr_number?: number | null
    baseline_hashes?: CreateRunInputApiBaselineHashes
    unchanged_count?: number
    removed_identifiers?: string[]
    purpose?: string
    metadata?: CreateRunInputApiMetadata
    is_partial?: boolean
}

export type UploadTargetApiFields = { [key: string]: string }

export interface UploadTargetApi {
    content_hash: string
    url: string
    fields: UploadTargetApiFields
}

export interface CreateRunResultApi {
    run_id: string
    uploads: UploadTargetApi[]
}

export type AddSnapshotsInputApiBaselineHashes = { [key: string]: string }

export interface AddSnapshotsInputApi {
    snapshots: SnapshotManifestItemApi[]
    baseline_hashes?: AddSnapshotsInputApiBaselineHashes
}

export interface AddSnapshotsResultApi {
    added: number
    uploads: UploadTargetApi[]
}

export interface ApproveSnapshotInputApi {
    /** The snapshot identifier to approve (e.g. Storybook story id plus theme). */
    identifier: string
    /** The content hash of the new baseline image to record for this identifier. */
    new_hash: string
}

export interface ApproveRunRequestInputApi {
    /** Snapshots to mark reviewed, each with `identifier` and `new_hash`. This only records the review in the database (the per-snapshot "Accept change" action) — it does not change the baseline or the GitHub gate. Commit the baseline and green the gate with the finalize endpoint. */
    snapshots: ApproveSnapshotInputApi[]
}

export interface FinalizeRunRequestInputApi {
    /** Approve every still-pending changed and new snapshot before finalizing (tolerated snapshots are left untouched). Leave false to finalize a run you've already reviewed — finalizing fails if any changed/new snapshot is still unreviewed. */
    approve_all?: boolean
    /** Whether the server commits the approved baseline to the PR branch and greens the gate (the normal path — leave true). Set false only for tooling that commits the baseline itself: the server skips the commit and returns the signed YAML in `baseline_content` instead. With false, the gate is NOT greened and `metadata.baseline_commit_sha` is absent. */
    commit_to_github?: boolean
    /** Whether to embed the before/after snapshot images in the post-approval PR comment. The comment itself is always posted (when the run was initiated from a GitHub review prompt and the repo has PR comments enabled); this flag only controls the images. Defaults false — the comment stays a text summary unless the reviewer opts in to attach the snapshots. */
    add_images_to_comment_on_pr?: boolean
}

export interface FinalizeResultApi {
    run: RunApi
    baseline_content: string
}

export interface RecomputeResultApi {
    run: RunApi
    counts_changed: boolean
    unresolved: number
    ci_rerun_triggered: boolean
    /** @nullable */
    ci_rerun_error?: string | null
}

export interface DiffClusterApi {
    x: number
    y: number
    width: number
    height: number
    pixel_count: number
    centroid_x: number
    centroid_y: number
}

export interface ClusterSummaryApi {
    items: DiffClusterApi[]
    total: number
    truncated: boolean
}

export type SnapshotApiMetadata = { [key: string]: unknown }

export interface SnapshotApi {
    current_artifact?: ArtifactApi | null
    baseline_artifact?: ArtifactApi | null
    diff_artifact?: ArtifactApi | null
    reviewed_by?: UserBasicInfoApi | null
    cluster_summary?: ClusterSummaryApi | null
    id: string
    run_id: string
    identifier: string
    result: string
    classification_reason: string
    /** @nullable */
    diff_percentage: number | null
    /** @nullable */
    diff_pixel_count: number | null
    review_state: string
    /** @nullable */
    reviewed_at: string | null
    approved_hash: string
    /** @nullable */
    tolerated_hash_id?: string | null
    is_quarantined?: boolean
    metadata?: SnapshotApiMetadata
    /** @nullable */
    ssim_score?: number | null
    change_kind?: string
    size_mismatch?: boolean
}

export interface PaginatedSnapshotListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SnapshotApi[]
    /** Count of this run's snapshots whose identifier is currently quarantined. Excluded from results unless include_quarantined=true is passed. */
    quarantined_count?: number
}

export interface MarkToleratedInputApi {
    /** UUID of the changed snapshot to mark as a known tolerated alternate. Future runs that produce the same alternate hash for this identifier will not be flagged as changes. */
    snapshot_id: string
}

export interface ToleratedHashEntryApi {
    id: string
    alternate_hash: string
    baseline_hash: string
    reason: string
    /** @nullable */
    diff_percentage: number | null
    created_at: string
    /** @nullable */
    source_run_id: string | null
}

export interface PaginatedToleratedHashEntryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ToleratedHashEntryApi[]
}

export type VisualReviewReposListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type VisualReviewReposQuarantineListParams = {
    /**
     * Filter by identifier (returns full history)
     */
    identifier?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by run type
     */
    run_type?: string
}

export type VisualReviewReposThumbnailsRetrieveParams = {
    /**
     * Narrow the lookup to one run type. The same identifier under two run types is two different images, so omit this only when the caller shows one run type.
     */
    run_type?: string
}

export type VisualReviewReposRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by review state
     */
    review_state?: string
    /**
     * Free-text search over branch, commit SHA, run type, and PR number
     */
    search?: string
}

export type VisualReviewReposSnapshotsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type VisualReviewRunsListParams = {
    /**
     * Filter by branch name
     */
    branch?: string
    /**
     * Filter by full commit SHA
     */
    commit_sha?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by GitHub PR number
     */
    pr_number?: number
    /**
     * Filter by review state
     */
    review_state?: string
    /**
     * Free-text search over branch, commit SHA, run type, and PR number
     */
    search?: string
}

export type VisualReviewRunsSnapshotHistoryListParams = {
    /**
     * Snapshot identifier
     */
    identifier: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type VisualReviewRunsSnapshotsListParams = {
    /**
     * Whether to include snapshots whose identifier is currently quarantined. Defaults to false: quarantined snapshots are excluded from results and reported in quarantined_count instead, since they are noise when reviewing real changes.
     */
    include_quarantined?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type VisualReviewRunsToleratedHashesListParams = {
    /**
     * Snapshot identifier
     */
    identifier: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
