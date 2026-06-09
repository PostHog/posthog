import { JSX, memo, useEffect, useRef, useState } from 'react'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import type { UserMessageAttachment } from '../buildConversationItems'
import { IconCheck, IconChevronDown, IconCopy, IconDocument } from '../primitives/icons'
import { MarkdownMessage } from '../primitives/MarkdownMessage'
import { hasFileMentions, parseFileMentions } from '../primitives/parseFileMentions'

export type { UserMessageAttachment }

const COLLAPSED_MAX_HEIGHT = 160

interface UserMessageProps {
    content: string
    timestamp?: number
    sourceUrl?: string
    attachments?: UserMessageAttachment[]
    animate?: boolean
}

function formatTimestamp(ts: number): string {
    return new Date(ts).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
    })
}

/** Static, non-clickable chip used for user message attachments. */
function AttachmentChip({ label }: { label: string }): JSX.Element {
    return (
        <span className="inline-flex min-w-0 max-w-full items-center gap-1 rounded bg-accent-highlight px-1 py-px align-middle text-[13px] font-medium text-accent">
            <IconDocument className="flex-shrink-0" style={{ fontSize: 12 }} />
            <span className="truncate">{label}</span>
        </span>
    )
}

/**
 * Right-aligned user message bubble for the read-only transcript.
 *
 * Memoized because the conversation renderer renders user messages directly
 * (not under a memoized row), so without `memo` every visible user message
 * would re-run markdown parsing on each parent render. Props are referentially
 * stable for completed turns, so `memo` skips re-renders.
 *
 * The `animate` prop is accepted for API parity with the reference but is a
 * no-op here — the read-only transcript has no entry animation (no
 * framer-motion dependency).
 */
export const UserMessage = memo(function UserMessage({
    content,
    timestamp,
    sourceUrl,
    attachments = [],
}: UserMessageProps): JSX.Element {
    const containsFileMentions = hasFileMentions(content)
    const showAttachmentChips = attachments.length > 0 && !containsFileMentions
    const [copied, setCopied] = useState(false)
    const [isExpanded, setIsExpanded] = useState(false)
    const [isOverflowing, setIsOverflowing] = useState(false)
    const contentRef = useRef<HTMLDivElement>(null)
    const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

    useEffect(() => {
        const el = contentRef.current
        if (el) {
            setIsOverflowing(el.scrollHeight > COLLAPSED_MAX_HEIGHT)
        }
    }, [])

    useEffect(() => {
        return () => clearTimeout(copiedTimerRef.current)
    }, [])

    const handleCopy = (): void => {
        void navigator.clipboard.writeText(content)
        setCopied(true)
        clearTimeout(copiedTimerRef.current)
        copiedTimerRef.current = setTimeout(() => setCopied(false), 2000)
    }

    return (
        <div className="group/msg relative border-l-2 border-accent bg-bg-light py-2 pl-3">
            <div
                ref={contentRef}
                className="relative overflow-hidden text-[13px] font-medium [&>*:last-child]:mb-0 [&_p]:leading-[1.9]"
                style={!isExpanded && isOverflowing ? { maxHeight: COLLAPSED_MAX_HEIGHT } : undefined}
            >
                {containsFileMentions ? parseFileMentions(content) : <MarkdownMessage content={content} />}
                {showAttachmentChips && (
                    <div className={`flex flex-wrap gap-1 ${content.trim() ? 'mt-1.5' : ''}`}>
                        {attachments.map((attachment) => (
                            <AttachmentChip key={attachment.id} label={attachment.label} />
                        ))}
                    </div>
                )}
                {!isExpanded && isOverflowing && (
                    <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-bg-light to-transparent" />
                )}
            </div>
            {isOverflowing && (
                <button
                    type="button"
                    onClick={() => setIsExpanded((prev) => !prev)}
                    className="mt-1 inline-flex items-center gap-1 text-[12px] text-accent hover:text-accent-highlight"
                >
                    <IconChevronDown className={isExpanded ? 'rotate-180' : undefined} style={{ fontSize: 12 }} />
                    {isExpanded ? 'Show less' : 'Show more'}
                </button>
            )}
            {sourceUrl && (
                <span className="mt-1.5 inline-flex items-center gap-1 text-[12px] text-muted">
                    <IconDocument style={{ fontSize: 12 }} />
                    <span>View source thread</span>
                </span>
            )}
            <div className="absolute right-1 top-1 flex select-none items-center gap-1.5 rounded-md bg-bg-light py-0.5 pl-2 pr-1 opacity-0 shadow-sm transition-opacity group-hover/msg:opacity-100">
                {timestamp != null && (
                    <span aria-hidden className="text-[11px] text-muted">
                        {formatTimestamp(timestamp)}
                    </span>
                )}
                <Tooltip title={copied ? 'Copied!' : 'Copy message'}>
                    <LemonButton
                        size="small"
                        icon={copied ? <IconCheck className="text-success" /> : <IconCopy />}
                        onClick={handleCopy}
                        aria-label="Copy message"
                    />
                </Tooltip>
            </div>
        </div>
    )
})
