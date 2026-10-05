import { useEffect, useId, useRef, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { Text, cn } from '@posthog/quill'

import { MarkdownMessage } from 'products/posthog_ai/frontend/api/primitives'

interface SpaceFeedCardPromptProps {
    taskId: string
    prompt: string
}

export function SpaceFeedCardPrompt({ taskId, prompt }: SpaceFeedCardPromptProps): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [overflowing, setOverflowing] = useState(false)
    const clampRef = useRef<HTMLDivElement>(null)
    const contentId = useId()

    useEffect(() => {
        const element = clampRef.current
        if (expanded || !element) {
            return
        }
        const observer = new ResizeObserver(() => setOverflowing(element.scrollHeight - element.clientHeight > 1))
        observer.observe(element)
        return () => observer.disconnect()
    }, [expanded, prompt])

    if (!prompt) {
        return (
            <Text size="xs" variant="muted" className="mt-1.5 leading-normal">
                A new task was started
            </Text>
        )
    }

    return (
        <div className="mt-1.5 flex min-w-0 flex-col items-start gap-1">
            {expanded ? (
                <div id={contentId} className="relative w-full min-w-0 text-xs leading-normal text-muted-foreground">
                    <MarkdownMessage content={prompt} id={`space-feed-prompt-${taskId}`} />
                </div>
            ) : (
                <Text
                    render={<p ref={clampRef} id={contentId} />}
                    size="xs"
                    variant="muted"
                    className="line-clamp-2 leading-normal break-words"
                >
                    {prompt}
                </Text>
            )}
            {(overflowing || expanded) && (
                <button
                    type="button"
                    aria-expanded={expanded}
                    aria-controls={contentId}
                    onClick={() => setExpanded(!expanded)}
                    className="relative flex items-center gap-0.5 rounded-sm text-xs text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                    data-attr="today-space-feed-card-prompt-toggle"
                >
                    <span>{expanded ? 'Show less' : 'Show full prompt'}</span>
                    <IconChevronDown className={cn('size-3', expanded && 'rotate-180')} />
                </button>
            )}
        </div>
    )
}
