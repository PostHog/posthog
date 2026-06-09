import { JSX } from 'react'

import { IconClock } from '@posthog/icons'

import { QueuedMessage } from '../acp-types'
import { MarkdownMessage } from '../primitives/MarkdownMessage'
import { hasFileMentions, parseFileMentions } from '../primitives/parseFileMentions'

interface QueuedMessageViewProps {
    message: QueuedMessage
    /** Ignored in the read-only transcript — kept for source parity. */
    onRemove?: () => void
}

/**
 * A user message that has been queued but not yet sent to the agent. Rendered
 * with muted, dashed-border styling to convey its pending state. The transcript
 * is read-only, so the remove affordance from the live app is not wired up.
 */
export function QueuedMessageView({ message }: QueuedMessageViewProps): JSX.Element {
    return (
        <div className="group relative border-l-2 border-dashed border-border bg-surface-secondary py-2 pr-2 pl-3 opacity-70">
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1 text-[13px] font-medium [&>*:last-child]:mb-0">
                    {hasFileMentions(message.content) ? (
                        parseFileMentions(message.content)
                    ) : (
                        <MarkdownMessage content={message.content} />
                    )}
                </div>
            </div>
            <div className="mt-1 flex items-center gap-1">
                <IconClock className="text-muted" style={{ fontSize: 12 }} />
                <span className="text-[13px] text-muted">Queued</span>
            </div>
        </div>
    )
}
