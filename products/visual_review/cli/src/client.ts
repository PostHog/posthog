/**
 * Visual Review API client.
 *
 * Simple fetch-based implementation for CLI usage.
 * Uses generated types from the frontend package.
 */
import type {
    ApproveSnapshotInputApi,
    ArtifactApi,
    AutoApproveResultApi,
    CreateRunInputApi,
    CreateRunResultApi,
    RunApi,
    SnapshotApi,
    SnapshotManifestItemApi,
    UploadTargetApi,
} from '@visual-review/types'

// Re-export types for convenience
export type {
    ArtifactApi as Artifact,
    CreateRunResultApi as CreateRunResult,
    RunApi as Run,
    SnapshotApi as Snapshot,
    SnapshotManifestItemApi as SnapshotManifestItem,
    UploadTargetApi as UploadTarget,
}

const RETRY_STATUS_CODES = new Set([500, 502, 503, 504])
const MAX_RETRIES = 3
const BASE_DELAY_MS = 1_000

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
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
            this.headers['Authorization'] = `Bearer ${config.token.trim()}`
        } else if (config.sessionCookie) {
            this.headers['Cookie'] = config.sessionCookie
        }
    }

    private url(path: string): string {
        return `${this.apiUrl}/api/projects/${this.teamId}${path}`
    }

    private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
        for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            const response = await fetch(this.url(path), {
                ...options,
                headers: {
                    ...this.headers,
                    ...options.headers,
                },
            })

            if (response.ok) {
                return response.json() as Promise<T>
            }

            const text = await response.text()

            if (RETRY_STATUS_CODES.has(response.status) && attempt < MAX_RETRIES) {
                const jitter = 0.75 + Math.random() * 0.5
                const delay = BASE_DELAY_MS * Math.pow(2, attempt) * jitter
                console.error(
                    `VR API returned ${response.status}, retrying in ${Math.round(delay)}ms (attempt ${attempt + 1}/${MAX_RETRIES})...`
                )
                await sleep(delay)
                continue
            }

            throw new Error(`API error ${response.status}: ${text}`)
        }

        throw new Error('Unexpected: exhausted retries')
    }

    /**
     * Create a new visual review run.
     */
    async createRun(input: {
        repoId: string
        runType: string
        commitSha: string
        branch: string
        snapshots: SnapshotManifestItemApi[]
        prNumber?: number
        purpose?: string
    }): Promise<CreateRunResultApi> {
        const body: CreateRunInputApi = {
            repo_id: input.repoId,
            run_type: input.runType,
            commit_sha: input.commitSha,
            branch: input.branch,
            snapshots: input.snapshots,
            pr_number: input.prNumber,
            purpose: input.purpose,
        }

        return this.request<CreateRunResultApi>('/visual_review/runs/', {
            method: 'POST',
            body: JSON.stringify(body),
        })
    }

    /**
     * Upload artifact to S3 using presigned URL from createRun response.
     */
    async uploadToS3(uploadTarget: UploadTargetApi, data: Buffer): Promise<void> {
        const formData = new FormData()

        // Add all presigned fields
        for (const [key, value] of Object.entries(uploadTarget.fields) as [string, string][]) {
            formData.append(key, value)
        }

        // Content-Type must be in form data (required by presigned POST policy)
        formData.append('Content-Type', 'image/png')

        // Add file data (must be last field in form data for S3)
        formData.append('file', new Blob([new Uint8Array(data)], { type: 'image/png' }))

        const response = await fetch(uploadTarget.url, {
            method: 'POST',
            body: formData,
        })

        if (!response.ok) {
            throw new Error(`S3 upload failed: ${response.status}`)
        }
    }

    /**
     * Add a batch of snapshots to an existing run (shard-based flow).
     */
    async addSnapshots(
        runId: string,
        input: {
            snapshots: SnapshotManifestItemApi[]
        }
    ): Promise<{ added: number; uploads: UploadTargetApi[] }> {
        return this.request(`/visual_review/runs/${runId}/add-snapshots/`, {
            method: 'POST',
            body: JSON.stringify({
                snapshots: input.snapshots,
            }),
        })
    }

    /**
     * Complete a run: detect removals, verify uploads, trigger diff processing.
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

    /**
     * Auto-approve all changes in a run and get signed baseline YAML.
     */
    async autoApproveRun(runId: string): Promise<AutoApproveResultApi> {
        return this.request<AutoApproveResultApi>(`/visual_review/runs/${runId}/auto-approve/`, {
            method: 'POST',
        })
    }
}
