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
            <span
                tabIndex={0}
                aria-label={`Comment on ${context.label}`}
                className="inline-flex max-w-60 min-w-0 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                data-attr="posthog-ai-comment-context-chip"
            >
                <LemonTag
                    icon={<IconComment />}
                    onClose={onRemove}
                    closable={!!onRemove}
                    className="flex min-w-0 items-center text-secondary"
                >
                    <span className="min-w-0 flex-1 truncate">{context.label}</span>
                </LemonTag>
            </span>
        </Tooltip>
    )
}
