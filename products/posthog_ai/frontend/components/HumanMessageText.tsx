import { useValues } from 'kea'
import { useMemo } from 'react'

import { projectLogic } from 'scenes/projectLogic'

import { stripInjectedBlocks } from 'products/tasks/frontend/spaces/spaceFeedPreview'

import { threadAttachmentDownloadUrl, useLocalPreviewUrl } from '../hooks/useThreadAttachmentUrl'
import { MarkdownMessage } from '../messages/MarkdownMessage'
import type { ThreadAttachment } from '../types/streamTypes'
import { type CommentContext, splitCommentContexts } from '../utils/commentContext'
import { userMessageDisplayText } from '../utils/userMessageDisplay'
import { CommentContextChip } from './CommentContextChip'

function SentCommentContextChip({
    context,
    attachments,
}: {
    context: CommentContext
    attachments: ThreadAttachment[]
}): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const attachment = context.screenshot
        ? attachments.find((candidate) => candidate.name === context.screenshot)
        : undefined
    const localUrl = useLocalPreviewUrl(attachment?.previewId)
    const downloadUrl =
        attachment && currentProjectId !== null
            ? threadAttachmentDownloadUrl(String(currentProjectId), attachment)
            : null
    return <CommentContextChip context={context} screenshotUrl={downloadUrl ?? localUrl} />
}

export function HumanMessageText({
    text,
    id,
    attachments = [],
}: {
    text: string
    id: string
    attachments?: ThreadAttachment[]
}): JSX.Element {
    const segments = useMemo(() => splitCommentContexts(stripInjectedBlocks(text)), [text])
    if (segments.length === 1 && segments[0].type === 'text') {
        const display = userMessageDisplayText(segments[0].text)
        return <MarkdownMessage content={display || '*No text.*'} id={id} />
    }
    return (
        <div className="flex flex-col items-start gap-1">
            {segments.map((segment, index) =>
                segment.type === 'comment_context' ? (
                    <SentCommentContextChip key={index} context={segment} attachments={attachments} />
                ) : (
                    <MarkdownMessage key={index} content={userMessageDisplayText(segment.text)} id={`${id}-${index}`} />
                )
            )}
        </div>
    )
}
