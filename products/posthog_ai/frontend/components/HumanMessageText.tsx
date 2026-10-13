import { useMemo } from 'react'

import { stripInjectedBlocks } from 'products/tasks/frontend/spaces/spaceFeedPreview'

import { MarkdownMessage } from '../messages/MarkdownMessage'
import { splitCommentContexts } from '../utils/commentContext'
import { userMessageDisplayText } from '../utils/userMessageDisplay'
import { CommentContextChip } from './CommentContextChip'

export function HumanMessageText({ text, id }: { text: string; id: string }): JSX.Element {
    const segments = useMemo(() => splitCommentContexts(stripInjectedBlocks(text)), [text])
    if (segments.length === 1 && segments[0].type === 'text') {
        const display = userMessageDisplayText(segments[0].text)
        return <MarkdownMessage content={display || '*No text.*'} id={id} />
    }
    return (
        <div className="flex flex-col items-start gap-1">
            {segments.map((segment, index) =>
                segment.type === 'comment_context' ? (
                    <CommentContextChip key={index} context={segment} />
                ) : (
                    <MarkdownMessage key={index} content={userMessageDisplayText(segment.text)} id={`${id}-${index}`} />
                )
            )}
        </div>
    )
}
