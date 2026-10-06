import {
    tasksRunsArtifactsFinalizeUploadCreate,
    tasksRunsArtifactsPrepareUploadCreate,
    tasksStagedArtifactsFinalizeUploadCreate,
    tasksStagedArtifactsPrepareUploadCreate,
} from 'products/tasks/frontend/generated/api'
import { TaskRunArtifactTypeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { inferContentType } from './attachments'

const ATTACHMENT_SOURCE = 'posthog_ai'

/** The staged and run-level endpoints take and return the same shapes, so one cycle serves both. */
interface ArtifactUploadEndpoints {
    prepare: (artifacts: PrepareRequest[]) => Promise<{ artifacts: PreparedArtifact[] }>
    finalize: (artifacts: FinalizeRequest[]) => Promise<unknown>
}

interface PrepareRequest {
    name: string
    type: typeof TaskRunArtifactTypeEnumApi.UserAttachment
    source: string
    size: number
    content_type: string
}

interface PreparedArtifact {
    id: string
    name: string
    type: string
    source?: string
    size: number
    content_type?: string
    storage_path: string
    presigned_post: { url: string; fields: Record<string, string> }
}

interface FinalizeRequest {
    id: string
    name: string
    type: typeof TaskRunArtifactTypeEnumApi.UserAttachment
    source: string
    storage_path: string
    content_type: string
}

function prepareRequestFor(file: File): PrepareRequest {
    return {
        name: file.name,
        type: TaskRunArtifactTypeEnumApi.UserAttachment,
        source: ATTACHMENT_SOURCE,
        size: file.size,
        content_type: inferContentType(file.name),
    }
}

async function uploadToPresignedPost(
    prepared: Pick<PreparedArtifact, 'name' | 'presigned_post'>,
    file: File
): Promise<void> {
    const formData = new FormData()
    // S3 requires the presigned fields verbatim and ahead of the file part.
    for (const [key, value] of Object.entries(prepared.presigned_post.fields)) {
        formData.append(key, value)
    }
    formData.append('file', file, prepared.name)

    const response = await fetch(prepared.presigned_post.url, { method: 'POST', body: formData })
    if (!response.ok) {
        throw new Error(`Couldn't upload ${prepared.name}`)
    }
}

/**
 * A single failure rejects the whole call: a message that silently arrives with fewer files than the user
 * attached is worse than one that refuses to send.
 */
async function uploadArtifacts(endpoints: ArtifactUploadEndpoints, files: File[]): Promise<string[]> {
    if (files.length === 0) {
        return []
    }

    const { artifacts: prepared } = await endpoints.prepare(files.map(prepareRequestFor))
    if (prepared.length !== files.length) {
        throw new Error("Couldn't prepare every attachment for upload")
    }

    await Promise.all(prepared.map((artifact, index) => uploadToPresignedPost(artifact, files[index])))

    await endpoints.finalize(
        prepared.map((artifact) => ({
            id: artifact.id,
            name: artifact.name,
            type: TaskRunArtifactTypeEnumApi.UserAttachment,
            source: ATTACHMENT_SOURCE,
            storage_path: artifact.storage_path,
            content_type: artifact.content_type ?? inferContentType(artifact.name),
        }))
    )

    return prepared.map((artifact) => artifact.id)
}

/** Hold files on a task whose run does not exist yet; the ids go to run create as `pending_user_artifact_ids`. */
export async function uploadStagedTaskAttachments(projectId: string, taskId: string, files: File[]): Promise<string[]> {
    return uploadArtifacts(
        {
            prepare: (artifacts) => tasksStagedArtifactsPrepareUploadCreate(projectId, taskId, { artifacts }),
            finalize: (artifacts) => tasksStagedArtifactsFinalizeUploadCreate(projectId, taskId, { artifacts }),
        },
        files
    )
}

/** Attach files to an existing run; the ids go to `user_message` as `params.artifact_ids`. */
export async function uploadRunAttachments(
    projectId: string,
    taskId: string,
    runId: string,
    files: File[]
): Promise<string[]> {
    return uploadArtifacts(
        {
            prepare: (artifacts) => tasksRunsArtifactsPrepareUploadCreate(projectId, taskId, runId, { artifacts }),
            finalize: (artifacts) => tasksRunsArtifactsFinalizeUploadCreate(projectId, taskId, runId, { artifacts }),
        },
        files
    )
}

/**
 * Save text as a new version of a run file, the same upload PostHog Desktop makes for an edit.
 * The artifacts tab groups uploads by file name, so the same name adds a version. Returns the new artifact id.
 */
export async function uploadRunOutputVersion(
    projectId: string,
    taskId: string,
    runId: string,
    { name, content, contentType }: { name: string; content: string; contentType: string }
): Promise<string> {
    const file = new File([content], name, { type: contentType })
    const {
        artifacts: [prepared],
    } = await tasksRunsArtifactsPrepareUploadCreate(projectId, taskId, runId, {
        artifacts: [{ name, type: TaskRunArtifactTypeEnumApi.Output, size: file.size, content_type: contentType }],
    })
    if (!prepared) {
        throw new Error(`Couldn't prepare ${name} for upload`)
    }
    await uploadToPresignedPost(prepared, file)
    const {
        artifacts: [finalized],
    } = await tasksRunsArtifactsFinalizeUploadCreate(projectId, taskId, runId, {
        artifacts: [
            {
                id: prepared.id,
                name: prepared.name,
                type: TaskRunArtifactTypeEnumApi.Output,
                storage_path: prepared.storage_path,
                content_type: contentType,
            },
        ],
    })
    if (!finalized?.id) {
        throw new Error(`Couldn't save ${name}`)
    }
    return finalized.id
}
