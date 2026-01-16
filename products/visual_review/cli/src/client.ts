/**
 * Visual Review API client.
 *
 * Simple fetch-based implementation for CLI usage.
 * Uses generated types from the frontend package.
 */
import type {
    ApproveSnapshotInputApi,
    ArtifactApi,
    CreateRunInputApi,
    CreateRunResultApi,
    RunApi,
    SnapshotApi,
    SnapshotManifestItemApi,
    UploadUrlApi,
} from '@visual-review/types'

// Re-export types for convenience
export type {
    ArtifactApi as Artifact,
    CreateRunResultApi as CreateRunResult,
    RunApi as Run,
    SnapshotApi as Snapshot,
    SnapshotManifestItemApi as SnapshotManifestItem,
    UploadUrlApi as UploadUrl,
}

export interface ClientConfig {
    apiUrl: string
    teamId: string
    token?: string
    sessionCookie?: string
}

export class VisualReviewClient {
    private apiUrl: string
    private teamId: string
    private headers: Record<string, string>

    constructor(config: ClientConfig) {
        this.apiUrl = config.apiUrl.replace(/\/$/, '')
        this.teamId = config.teamId
        this.headers = {
            'Content-Type': 'application/json',
        }
        if (config.token) {
            this.headers['Authorization'] = `Bearer ${config.token}`
        } else if (config.sessionCookie) {
            this.headers['Cookie'] = config.sessionCookie
        }
    }

    private url(path: string): string {
        return `${this.apiUrl}/api/projects/${this.teamId}${path}`
    }

    private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
        const response = await fetch(this.url(path), {
            ...options,
            headers: {
                ...this.headers,
                ...options.headers,
            },
        })

        if (!response.ok) {
            const text = await response.text()
            throw new Error(`API error ${response.status}: ${text}`)
        }

        return response.json() as Promise<T>
    }

    /**
     * Create a new visual review run.
     */
    async createRun(input: {
        projectId: string
        runType: string
        commitSha: string
        branch: string
        snapshots: SnapshotManifestItemApi[]
        prNumber?: number
        baselineHashes?: Record<string, string>
    }): Promise<CreateRunResultApi> {
        const body: CreateRunInputApi = {
            project_id: input.projectId,
            run_type: input.runType,
            commit_sha: input.commitSha,
            branch: input.branch,
            snapshots: input.snapshots,
            pr_number: input.prNumber,
            baseline_hashes: input.baselineHashes,
        }

        return this.request<CreateRunResultApi>('/visual_review/runs/', {
            method: 'POST',
            body: JSON.stringify(body),
        })
    }

    /**
     * Get presigned URL for uploading an artifact.
     */
    async getUploadUrl(projectId: string, contentHash: string): Promise<UploadUrlApi> {
        return this.request<UploadUrlApi>(`/visual_review/projects/${projectId}/upload-url/`, {
            method: 'POST',
            body: JSON.stringify({ content_hash: contentHash }),
        })
    }

    /**
     * Upload artifact to S3 using presigned URL.
     */
    async uploadToS3(uploadUrl: UploadUrlApi, data: Buffer): Promise<void> {
        const formData = new FormData()

        // Add all presigned fields
        for (const [key, value] of Object.entries(uploadUrl.fields)) {
            formData.append(key, value)
        }

        // Content-Type must be in form data (required by presigned POST policy)
        formData.append('Content-Type', 'image/png')

        // Add file data (must be last field in form data for S3)
        formData.append('file', new Blob([new Uint8Array(data)], { type: 'image/png' }))

        const response = await fetch(uploadUrl.url, {
            method: 'POST',
            body: formData,
        })

        if (!response.ok) {
            throw new Error(`S3 upload failed: ${response.status}`)
        }
    }

    /**
     * Register an artifact after upload.
     */
    async registerArtifact(
        projectId: string,
        contentHash: string,
        width?: number,
        height?: number,
        sizeBytes?: number
    ): Promise<void> {
        await this.request(`/visual_review/projects/${projectId}/artifacts/`, {
            method: 'POST',
            body: JSON.stringify({
                content_hash: contentHash,
                width,
                height,
                size_bytes: sizeBytes,
            }),
        })
    }

    /**
     * Signal that all artifacts are uploaded, trigger diff processing.
     */
    async completeRun(runId: string): Promise<RunApi> {
        return this.request<RunApi>(`/visual_review/runs/${runId}/complete/`, {
            method: 'POST',
        })
    }

    /**
     * Get run status and summary.
     */
    async getRun(runId: string): Promise<RunApi> {
        return this.request<RunApi>(`/visual_review/runs/${runId}/`)
    }

    /**
     * Get snapshots for a run.
     */
    async getRunSnapshots(runId: string): Promise<SnapshotApi[]> {
        return this.request<SnapshotApi[]>(`/visual_review/runs/${runId}/snapshots/`)
    }

    /**
     * Approve visual changes for a run.
     */
    async approveRun(runId: string, snapshots: ApproveSnapshotInputApi[]): Promise<RunApi> {
        return this.request<RunApi>(`/visual_review/runs/${runId}/approve/`, {
            method: 'POST',
            body: JSON.stringify({ snapshots }),
        })
    }
}
