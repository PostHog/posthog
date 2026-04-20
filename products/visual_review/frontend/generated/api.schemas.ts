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
export type PatchedUpdateRepoRequestInputApiBaselineFilePaths = { [key: string]: string } | null | null

export interface PatchedUpdateRepoRequestInputApi {
    /** @nullable */
    baseline_file_paths?: PatchedUpdateRepoRequestInputApiBaselineFilePaths
    /** @nullable */
    enable_pr_comments?: boolean | null
}

export interface RunSummaryApi {
    total: number
    changed: number
    new: number
    removed: number
    unchanged: number
    tolerated_matched?: number
}

export type RunApiMetadata = { [key: string]: unknown }

export interface RunApi {
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
    identifier: string
    new_hash: string
}

export interface ApproveRunRequestInputApi {
    snapshots?: ApproveSnapshotInputApi[]
    approve_all?: boolean
    commit_to_github?: boolean
}

export interface AutoApproveResultApi {
    run: RunApi
    baseline_content: string
}

export interface SnapshotHistoryEntryApi {
    run_id: string
    result: string
    branch: string
    commit_sha: string
    created_at: string
}

export interface PaginatedSnapshotHistoryEntryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SnapshotHistoryEntryApi[]
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

export type SnapshotApiMetadata = { [key: string]: unknown }

export interface SnapshotApi {
    current_artifact?: ArtifactApi | null
    baseline_artifact?: ArtifactApi | null
    diff_artifact?: ArtifactApi | null
    id: string
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
    metadata?: SnapshotApiMetadata
}

export interface PaginatedSnapshotListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SnapshotApi[]
}

export interface MarkToleratedInputApi {
    snapshot_id: string
}

export interface ToleratedHashEntryApi {
    id: string
    alternate_hash: string
    baseline_hash: string
    reason: string
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

export interface ReviewStateCountsApi {
    needs_review: number
    clean: number
    processing: number
    stale: number
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

export type VisualReviewRunsListParams = {
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
