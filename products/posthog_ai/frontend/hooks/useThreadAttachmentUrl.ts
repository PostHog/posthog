import { useEffect, useState } from 'react'

import { getTasksRunsArtifactsDownloadRetrieveUrl } from 'products/tasks/frontend/generated/api'

import type { ThreadAttachment } from '../types/streamTypes'
import { getAttachmentPreview } from '../utils/attachmentPreviews'

/** The endpoint redirects to a presigned URL and takes the session, so an `img` and an `a` use it directly. */
export function threadAttachmentDownloadUrl(projectId: string, attachment: ThreadAttachment): string | null {
    if (!attachment.taskId || !attachment.runId || !attachment.artifactId) {
        return null
    }
    // The run that holds the artifact, not necessarily the one being read: a resume chain reaches back.
    return getTasksRunsArtifactsDownloadRetrieveUrl(
        projectId,
        attachment.taskId,
        attachment.runId,
        attachment.artifactId
    )
}

export function useFileObjectUrl(file: File | undefined): string | null {
    const [url, setUrl] = useState<string | null>(null)
    useEffect(() => {
        if (!file) {
            setUrl(null)
            return
        }
        const objectUrl = URL.createObjectURL(file)
        setUrl(objectUrl)
        return () => URL.revokeObjectURL(objectUrl)
    }, [file])
    return url
}

/** The staged file's own bytes, available from the send until its upload lands. */
export function useLocalPreviewUrl(previewId: string | undefined): string | null {
    return useFileObjectUrl(getAttachmentPreview(previewId))
}
