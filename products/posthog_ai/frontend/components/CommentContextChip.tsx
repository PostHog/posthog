import { useEffect, useState } from 'react'

import { IconComment } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { type CommentContext, commentContextPreview } from '../utils/commentContext'

export function CommentContextChip({
    context,
    screenshotUrl,
    onRemove,
}: {
    context: CommentContext
    screenshotUrl?: string | null
    onRemove?: () => void
}): JSX.Element {
    const [screenshotFailed, setScreenshotFailed] = useState(false)
    useEffect(() => setScreenshotFailed(false), [screenshotUrl])
    return (
        <Tooltip
            title={
                <div className="flex max-w-80 flex-col gap-1">
                    {screenshotUrl && !screenshotFailed && (
                        <img
                            src={screenshotUrl}
                            alt={`Screenshot of ${context.label}`}
                            className="max-h-48 rounded"
                            onError={() => setScreenshotFailed(true)}
                        />
                    )}
                    <div className="whitespace-pre-wrap break-words text-xs">{commentContextPreview(context)}</div>
                </div>
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
