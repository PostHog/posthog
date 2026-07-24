import { memo } from 'react'

import { IconCopy, IconTerminal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

export interface DebugMessageProps {
    text: string
    level: string
    /** Render as a single truncated line with an always-visible button copying the full raw text. */
    copyable?: boolean
}

const LEVEL_STYLES: Record<string, string> = {
    error: 'border-l-danger text-danger',
    warn: 'border-l-warning text-warning',
    debug: 'border-l-muted',
    info: 'border-l-muted',
    context: 'border-l-accent',
}

/**
 * Inline console line rendered from `_posthog/console` wire frames, plus the copyable
 * `debugLevel: 'context'` rows carrying a send's attached-context blocks. Not a chat bubble — a
 * muted, monospace debug row visually distinct from assistant failures (`AssistantFailureMessage`).
 * Whether these rows surface at all is gated upstream by `debugLogsLogic.showDebugLogs` (staff/dev
 * toggle, always on when impersonating).
 */
export const DebugMessage = memo(function DebugMessage({ text, level, copyable }: DebugMessageProps): JSX.Element {
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
            {copyable ? (
                <>
                    <span className="min-w-0 flex-1 truncate" title={text}>
                        {text.replace(/\s*\n\s*/g, ' ')}
                    </span>
                    <LemonButton
                        size="xsmall"
                        icon={<IconCopy />}
                        tooltip="Copy"
                        onClick={() => void copyToClipboard(text, 'context block')}
                        className="shrink-0 -my-1"
                    />
                </>
            ) : (
                <span className="min-w-0 flex-1 whitespace-pre-wrap [overflow-wrap:anywhere]">{text}</span>
            )}
        </div>
    )
})
