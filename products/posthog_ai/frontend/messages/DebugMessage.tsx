import { memo } from 'react'

import { IconTerminal } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

export interface DebugMessageProps {
    text: string
    level: string
}

const LEVEL_STYLES: Record<string, string> = {
    error: 'border-l-danger text-danger',
    warn: 'border-l-warning text-warning',
    debug: 'border-l-muted',
    info: 'border-l-muted',
}

/**
 * Staff-only inline console line rendered from `_posthog/console` wire frames. Not a chat bubble —
 * a muted, monospace debug row visually distinct from assistant failures (`AssistantFailureMessage`).
 */
export const DebugMessage = memo(function DebugMessage({ text, level }: DebugMessageProps): JSX.Element {
    const levelStyle = LEVEL_STYLES[level] ?? LEVEL_STYLES.info
    return (
        <div
            className={cn(
                'flex items-start gap-1.5 w-full min-w-0 py-1 px-2 text-xs text-muted',
                'border-l-2 bg-surface-tertiary/50 font-mono',
                levelStyle
            )}
            data-message-type="debug"
            data-debug-level={level}
        >
            <IconTerminal className="size-3 shrink-0 mt-0.5 opacity-70" />
            <span className="min-w-0 flex-1 whitespace-pre-wrap [overflow-wrap:anywhere]">{text}</span>
        </div>
    )
})
