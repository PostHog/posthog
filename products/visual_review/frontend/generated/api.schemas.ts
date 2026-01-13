/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ProjectApi {
    id: string
    team_id: number
    name: string
    created_at: string
}

export interface PaginatedProjectListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ProjectApi[]
}

/**
 * Notification that an artifact has been uploaded.
 */
export interface ArtifactUploadedApi {
    /** @maxLength 128 */
    content_hash: string
    /** @nullable */
    width?: number | null
    /** @nullable */
    height?: number | null
    /** @nullable */
    size_bytes?: number | null
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

/**
 * Request for a presigned upload URL.
 */
export interface UploadUrlRequestApi {
    /** @maxLength 128 */
    content_hash: string
}

export type UploadUrlApiFields = { [key: string]: string }

export interface UploadUrlApi {
    url: string
    fields: UploadUrlApiFields
}

export type CreateRunInputApiBaselineHashes = { [key: string]: string }

export interface SnapshotManifestItemApi {
    identifier: string
    content_hash: string
    /** @nullable */
    width?: number | null
    /** @nullable */
    height?: number | null
}

export interface CreateRunInputApi {
    project_id: string
    run_type: string
    commit_sha: string
    branch: string
    snapshots: SnapshotManifestItemApi[]
    /** @nullable */
    pr_number?: number | null
    baseline_hashes?: CreateRunInputApiBaselineHashes
}

export interface CreateRunResultApi {
    run_id: string
    missing_hashes: string[]
}

export interface RunSummaryApi {
    total: number
    changed: number
    new: number
    removed: number
    unchanged: number
}

export interface RunApi {
    id: string
    project_id: string
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
}

export interface ApproveSnapshotInputApi {
    identifier: string
    new_hash: string
}

/**
 * Input for approving a run.
 */
export interface ApproveRunInputApi {
    snapshots: ApproveSnapshotInputApi[]
}

export interface SnapshotApi {
    id: string
    identifier: string
    result: string
    current_artifact: ArtifactApi
    baseline_artifact: ArtifactApi
    diff_artifact: ArtifactApi
    /** @nullable */
    diff_percentage: number | null
    /** @nullable */
    diff_pixel_count: number | null
}

export interface PaginatedSnapshotListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SnapshotApi[]
}

export type VisualReviewProjectsListParams = {
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
