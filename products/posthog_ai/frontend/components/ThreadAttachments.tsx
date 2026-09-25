import { useValues } from 'kea'
import { memo, useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { projectLogic } from 'scenes/projectLogic'

import { getTasksRunsArtifactsDownloadRetrieveUrl } from 'products/tasks/frontend/generated/api'

import type { ThreadAttachment } from '../types/streamTypes'
import { isImageAttachment } from '../utils/attachments'

// Capped on both axes and free to shrink, so no screenshot pushes a message past its panel.
const THUMBNAIL_CLASSES = 'max-h-48 max-w-full w-auto rounded border border-primary object-contain'

/** The endpoint redirects to a presigned URL and takes the session, so an `img` and an `a` use it directly. */
function downloadUrl(projectId: string, attachment: ThreadAttachment): string | null {
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

function AttachmentChip({ name, href }: { name: string; href: string | null }): JSX.Element {
    const chip = (
        <LemonTag icon={<IconDocument />} className="max-w-48">
            <span className="truncate min-w-0">{name}</span>
        </LemonTag>
    )
    return (
        <Tooltip title={href ? `Download ${name}` : name}>
            {href ? (
                // An API path is not an app route, so client-side routing has to stay out of it.
                <Link to={href} target="_blank" disableClientSideRouting targetBlankIcon={false}>
                    {chip}
                </Link>
            ) : (
                <span>{chip}</span>
            )}
        </Tooltip>
    )
}

/** Until the ids arrive, an image holds its space so the message does not jump once they do. */
const ThreadAttachmentItem = memo(function ThreadAttachmentItem({
    attachment,
    projectId,
}: {
    attachment: ThreadAttachment
    projectId: string | null
}): JSX.Element {
    const [failed, setFailed] = useState(false)
    const href = projectId ? downloadUrl(projectId, attachment) : null

    if (!isImageAttachment(attachment.name) || failed) {
        return <AttachmentChip name={attachment.name} href={href} />
    }
    if (!href) {
        return <LemonSkeleton className="h-24 w-32 rounded shrink-0" />
    }
    return (
        <Tooltip title={attachment.name}>
            <Link
                to={href}
                target="_blank"
                disableClientSideRouting
                targetBlankIcon={false}
                className="min-w-0 max-w-full"
            >
                <img src={href} alt={attachment.name} className={THUMBNAIL_CLASSES} onError={() => setFailed(true)} />
            </Link>
        </Tooltip>
    )
})

export function ThreadAttachments({ attachments }: { attachments: ThreadAttachment[] }): JSX.Element | null {
    const { currentProjectId } = useValues(projectLogic)
    if (attachments.length === 0) {
        return null
    }
    return (
        <div className="flex flex-wrap items-start gap-1 mt-1 min-w-0 max-w-full">
            {attachments.map((attachment) => (
                <ThreadAttachmentItem
                    key={`${attachment.artifactId ?? 'pending'}-${attachment.name}`}
                    attachment={attachment}
                    projectId={currentProjectId === null ? null : String(currentProjectId)}
                />
            ))}
        </div>
    )
}
