import {
    tasksRunCreate,
    tasksRunsArtifactsFinalizeUploadCreate,
    tasksRunsArtifactsPrepareUploadCreate,
    tasksRunsCommandCreate,
    tasksStagedArtifactsFinalizeUploadCreate,
    tasksStagedArtifactsPrepareUploadCreate,
} from '../generated/api'
import {
    type ClaudeTaskRunCreateSchemaApi,
    type MethodEnumApi,
    type ReasoningEffortEnumApi,
    type S3PresignedPostApi,
    type TaskRunArtifactPrepareUploadApi,
    type TaskRunCommandRequestApiParams,
    type TaskRunCreateRequestSchemaApi,
    TaskRunArtifactTypeEnumApi,
} from '../generated/api.schemas'

/** Max upload size enforced by the backend prepare endpoint (30 MiB). */
export const CLOUD_ATTACHMENT_MAX_SIZE_BYTES = 30 * 1024 * 1024
/** Tighter cap PDFs are held to, matching the reference app. */
export const CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES = 10 * 1024 * 1024

const CONTENT_TYPE_BY_EXTENSION: Record<string, string> = {
    css: 'text/css',
    csv: 'text/csv',
    gif: 'image/gif',
    html: 'text/html',
    jpeg: 'image/jpeg',
    jpg: 'image/jpeg',
    js: 'text/javascript',
    json: 'application/json',
    md: 'text/markdown',
    pdf: 'application/pdf',
    png: 'image/png',
    svg: 'image/svg+xml',
    txt: 'text/plain',
    webp: 'image/webp',
    yaml: 'application/yaml',
    yml: 'application/yaml',
}

function getExtension(name: string): string {
    const parts = name.split('.')
    return parts.length > 1 ? (parts.at(-1)?.toLowerCase() ?? '') : ''
}

function inferContentType(file: File): string {
    return file.type || CONTENT_TYPE_BY_EXTENSION[getExtension(file.name)] || 'application/octet-stream'
}

function maxSizeFor(file: File, contentType: string): number {
    if (getExtension(file.name) === 'pdf' || contentType.split(';')[0]?.trim().toLowerCase() === 'application/pdf') {
        return CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES
    }
    return CLOUD_ATTACHMENT_MAX_SIZE_BYTES
}

/** Send a JSON-RPC command to the agent server running a cloud task. */
export async function sendRunCommand(
    projectId: string,
    taskId: string,
    runId: string,
    method: MethodEnumApi,
    params?: TaskRunCommandRequestApiParams
): Promise<Record<string, unknown> | undefined> {
    const response = await tasksRunsCommandCreate(projectId, taskId, runId, {
        jsonrpc: '2.0',
        method,
        ...(params ? { params } : {}),
    })
    if (response.error) {
        const message = (response.error as { message?: string }).message ?? 'Command failed'
        throw new Error(message)
    }
    return response.result as Record<string, unknown> | undefined
}

function buildPrepareItems(files: File[]): TaskRunArtifactPrepareUploadApi[] {
    return files.map((file) => {
        const contentType = inferContentType(file)
        const maxBytes = maxSizeFor(file, contentType)
        if (file.size > maxBytes) {
            throw new Error(`${file.name} exceeds the ${Math.floor(maxBytes / (1024 * 1024))}MB attachment limit`)
        }
        return {
            name: file.name,
            type: TaskRunArtifactTypeEnumApi.UserAttachment,
            source: 'posthog_web',
            size: file.size,
            content_type: contentType,
        }
    })
}

interface PreparedArtifact {
    id: string
    name: string
    type: string
    source?: string
    storage_path: string
    content_type?: string
    presigned_post: S3PresignedPostApi
}

async function uploadToPresigned(prepared: PreparedArtifact[], files: File[]): Promise<void> {
    await Promise.all(
        prepared.map(async (artifact, index) => {
            const formData = new FormData()
            for (const [key, value] of Object.entries(artifact.presigned_post.fields)) {
                formData.append(key, value)
            }
            formData.append('file', files[index], artifact.name)
            const uploadResponse = await fetch(artifact.presigned_post.url, { method: 'POST', body: formData })
            if (!uploadResponse.ok) {
                throw new Error(`Failed to upload ${artifact.name}`)
            }
        })
    )
}

function finalizeItems(prepared: PreparedArtifact[]): {
    id: string
    name: string
    type: TaskRunArtifactTypeEnumApi
    source?: string
    storage_path: string
    content_type?: string
}[] {
    return prepared.map((artifact) => ({
        id: artifact.id,
        name: artifact.name,
        type: artifact.type as TaskRunArtifactTypeEnumApi,
        source: artifact.source,
        storage_path: artifact.storage_path,
        content_type: artifact.content_type,
    }))
}

/**
 * Upload browser-selected files as run artifacts and return their stable ids,
 * suitable for the `artifact_ids` param of a `user_message` command. Mirrors the
 * reference app's `uploadRunAttachments`: prepare → presigned S3 POST → finalize.
 */
export async function uploadRunAttachments(
    projectId: string,
    taskId: string,
    runId: string,
    files: File[]
): Promise<string[]> {
    if (files.length === 0) {
        return []
    }
    const prepared = await tasksRunsArtifactsPrepareUploadCreate(projectId, taskId, runId, {
        artifacts: buildPrepareItems(files),
    })
    await uploadToPresigned(prepared.artifacts, files)
    const finalized = await tasksRunsArtifactsFinalizeUploadCreate(projectId, taskId, runId, {
        artifacts: finalizeItems(prepared.artifacts),
    })
    return finalized.artifacts.map((artifact) => artifact.id).filter((id): id is string => typeof id === 'string')
}

/**
 * Upload files as task-level *staged* artifacts (used when resuming a terminal
 * run, which spins up a brand-new run that doesn't exist yet). Returns the
 * staged artifact ids for `pending_user_artifact_ids`.
 */
export async function uploadStagedAttachments(projectId: string, taskId: string, files: File[]): Promise<string[]> {
    if (files.length === 0) {
        return []
    }
    const prepared = await tasksStagedArtifactsPrepareUploadCreate(projectId, taskId, {
        artifacts: buildPrepareItems(files),
    })
    await uploadToPresigned(prepared.artifacts, files)
    const finalized = await tasksStagedArtifactsFinalizeUploadCreate(projectId, taskId, {
        artifacts: finalizeItems(prepared.artifacts),
    })
    return finalized.artifacts.map((artifact) => artifact.id).filter((id): id is string => typeof id === 'string')
}

export interface ResumeRunOptions {
    resumeFromRunId: string
    message: string
    artifactIds: string[]
    model?: string
    branch?: string | null
    reasoningEffort?: ReasoningEffortEnumApi
}

/**
 * Resume a terminal cloud run by creating a follow-up run that carries the
 * conversation history plus the new user message. Returns the new run id.
 */
export async function resumeRun(projectId: string, taskId: string, options: ResumeRunOptions): Promise<string | null> {
    const base = {
        resume_from_run_id: options.resumeFromRunId,
        pending_user_message: options.message,
        ...(options.branch ? { branch: options.branch } : {}),
    }
    // With a known model we send the full Claude schema (and can attach artifacts);
    // otherwise fall back to the resume schema, which inherits model/adapter from the
    // run being resumed.
    const body: TaskRunCreateRequestSchemaApi = options.model
        ? ({
              ...base,
              runtime_adapter: 'claude',
              model: options.model,
              ...(options.artifactIds.length > 0 ? { pending_user_artifact_ids: options.artifactIds } : {}),
              ...(options.reasoningEffort ? { reasoning_effort: options.reasoningEffort } : {}),
          } satisfies ClaudeTaskRunCreateSchemaApi)
        : base
    const task = await tasksRunCreate(projectId, taskId, body)
    return task.latest_run?.id ?? null
}
