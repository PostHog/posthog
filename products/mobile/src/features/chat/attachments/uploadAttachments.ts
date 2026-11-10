import { File } from 'expo-file-system'
import { Platform } from 'react-native'

import {
    type ArtifactUploadTarget,
    finalizeArtifactUpload,
    type PreparedArtifactApi,
    prepareArtifactUpload,
} from '@/api/tasks'

import type { PendingAttachment } from './types'

// The three-step upload of `products/posthog_ai/frontend/utils/artifactUpload.ts`: prepare, a presigned S3 POST per
// file, then finalize.

const ATTACHMENT_TYPE = 'user_attachment'
const ATTACHMENT_SOURCE = 'posthog_ai'

/** The presigned S3 POST, or the prepare answer, did not take a file. `status` is the S3 status, when there was one. */
export class AttachmentUploadError extends Error {
    readonly status: number | undefined

    constructor(message: string, status?: number) {
        super(message)
        this.name = 'AttachmentUploadError'
        this.status = status
    }
}

/** The global `fetch` is `expo/fetch`, which encodes only a `Blob`-like part and reads its file name and type from the
 * part, not from `append`, so the part carries the attachment's name and type instead of the on-disk ones. */
async function filePart(file: PendingAttachment): Promise<Blob> {
    if (Platform.OS === 'web') {
        return file.webFile ?? (await fetch(file.uri)).blob()
    }
    const onDisk = new File(file.uri)
    return { name: file.name, type: file.contentType, bytes: () => onDisk.bytes() } as unknown as Blob
}

async function postToS3(prepared: PreparedArtifactApi, file: PendingAttachment, signal?: AbortSignal): Promise<void> {
    const form = new FormData()
    // S3 needs the policy fields verbatim and before the file part.
    for (const [key, value] of Object.entries(prepared.presigned_post.fields)) {
        form.append(key, value)
    }
    form.append('file', await filePart(file), file.name)
    // A plain fetch, so the PostHog bearer token never goes to S3.
    const response = await fetch(prepared.presigned_post.url, { method: 'POST', body: form, signal })
    if (!response.ok) {
        throw new AttachmentUploadError(`Couldn't upload ${file.name}`, response.status)
    }
}

/**
 * Uploads every file and returns the artifact ids in the order of `files`. One failure rejects the whole batch,
 * because a message that arrives with fewer files than the person attached is worse than one that does not send.
 */
export async function uploadAttachments(
    target: ArtifactUploadTarget,
    files: readonly PendingAttachment[],
    signal?: AbortSignal
): Promise<string[]> {
    if (files.length === 0) {
        return []
    }
    const prepared = await prepareArtifactUpload(
        target,
        files.map((file) => ({
            name: file.name,
            type: ATTACHMENT_TYPE,
            source: ATTACHMENT_SOURCE,
            size: file.size,
            content_type: file.contentType,
        })),
        signal
    )
    if (prepared.length !== files.length) {
        throw new AttachmentUploadError("Couldn't prepare every attachment for upload")
    }
    // The first failed post fails the batch, so the other posts stop instead of uploading files nobody will finalize.
    const posts = new AbortController()
    const abortPosts = (): void => posts.abort()
    signal?.addEventListener('abort', abortPosts, { once: true })
    if (signal?.aborted) {
        posts.abort()
    }
    try {
        await Promise.all(
            prepared.map((artifact, index) =>
                postToS3(artifact, files[index] as PendingAttachment, posts.signal).catch((error: unknown) => {
                    posts.abort()
                    throw error
                })
            )
        )
    } finally {
        signal?.removeEventListener('abort', abortPosts)
    }
    await finalizeArtifactUpload(
        target,
        prepared.map((artifact, index) => ({
            id: artifact.id,
            name: artifact.name,
            type: ATTACHMENT_TYPE,
            source: ATTACHMENT_SOURCE,
            storage_path: artifact.storage_path,
            content_type: (files[index] as PendingAttachment).contentType,
        })),
        signal
    )
    return prepared.map((artifact) => artifact.id)
}
