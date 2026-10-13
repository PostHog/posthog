import { IconComment } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { type CommentContext, commentContextPreview } from '../utils/commentContext'

export function CommentContextChip({
    context,
    onRemove,
}: {
    context: CommentContext
    onRemove?: () => void
}): JSX.Element {
    return (
        <Tooltip
            title={
                <div className="max-w-80 whitespace-pre-wrap break-words text-xs">{commentContextPreview(context)}</div>
            }
        >
            <LemonTag
                icon={<IconComment />}
                onClose={onRemove}
                closable={!!onRemove}
                closeOnClick={!!onRemove}
                className="flex max-w-60 items-center text-secondary"
                data-attr="posthog-ai-comment-context-chip"
            >
                <span className="min-w-0 flex-1 truncate">{context.label}</span>
            </LemonTag>
        </Tooltip>
    )
}
