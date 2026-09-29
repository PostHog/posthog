import { useValues } from 'kea'
import { memo, useEffect, useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { projectLogic } from 'scenes/projectLogic'

import { getTasksRunsArtifactsDownloadRetrieveUrl } from 'products/tasks/frontend/generated/api'

import type { ThreadAttachment } from '../types/streamTypes'
import { getAttachmentPreview } from '../utils/attachmentPreviews'
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

/** The staged file's own bytes, available from the send until its upload lands. */
function useLocalPreviewUrl(previewId: string | undefined): string | null {
    const [url, setUrl] = useState<string | null>(null)
    useEffect(() => {
        const file = getAttachmentPreview(previewId)
        if (!file) {
            setUrl(null)
            return
        }
        const objectUrl = URL.createObjectURL(file)
        setUrl(objectUrl)
        return () => URL.revokeObjectURL(objectUrl)
    }, [previewId])
    return url
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

/** The artifact wins once it exists, so a message shows what the agent received. */
const ThreadAttachmentImage = memo(function ThreadAttachmentImage({
    attachment,
    href,
    onUnavailable,
}: {
    attachment: ThreadAttachment
    href: string | null
    onUnavailable: () => void
}): JSX.Element {
    const localUrl = useLocalPreviewUrl(attachment.previewId)
    const src = href ?? localUrl

    if (!src) {
        return <LemonSkeleton className="h-24 w-32 rounded shrink-0" />
    }
    const image = <img src={src} alt={attachment.name} className={THUMBNAIL_CLASSES} onError={onUnavailable} />
    return (
        <Tooltip title={attachment.name}>
            {href ? (
                <Link to={href} target="_blank" disableClientSideRouting targetBlankIcon={false} className="min-w-0">
                    {image}
                </Link>
            ) : (
                <span className="min-w-0">{image}</span>
            )}
        </Tooltip>
    )
})

function attachmentKey(attachment: ThreadAttachment): string {
    return `${attachment.artifactId ?? attachment.previewId ?? 'pending'}-${attachment.name}`
}

/** Images first, then a badge per remaining file, so a screenshot is not competing with a row of names. */
export function ThreadAttachments({ attachments }: { attachments: ThreadAttachment[] }): JSX.Element | null {
    const { currentProjectId } = useValues(projectLogic)
    // An unfetchable image moves down to the badges rather than leaving a broken frame.
    const [unavailable, setUnavailable] = useState<Set<string>>(new Set())

    if (attachments.length === 0) {
        return null
    }

    const projectId = currentProjectId === null ? null : String(currentProjectId)
    const showsImage = (attachment: ThreadAttachment): boolean =>
        isImageAttachment(attachment.name) && !unavailable.has(attachmentKey(attachment))
    const images = attachments.filter(showsImage)
    const files = attachments.filter((attachment) => !showsImage(attachment))

    return (
        <div className="flex flex-col gap-1 mt-1 min-w-0 max-w-full">
            {images.length > 0 && (
                <div className="flex flex-wrap items-start gap-1 min-w-0 max-w-full">
                    {images.map((attachment) => {
                        const key = attachmentKey(attachment)
                        return (
                            <ThreadAttachmentImage
                                key={key}
                                attachment={attachment}
                                href={projectId ? downloadUrl(projectId, attachment) : null}
                                onUnavailable={() => setUnavailable((seen) => new Set(seen).add(key))}
                            />
                        )
                    })}
                </div>
            )}
            {files.length > 0 && (
                <div className="flex flex-wrap items-center gap-1 min-w-0 max-w-full">
                    {files.map((attachment) => (
                        <AttachmentChip
                            key={attachmentKey(attachment)}
                            name={attachment.name}
                            href={projectId ? downloadUrl(projectId, attachment) : null}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
