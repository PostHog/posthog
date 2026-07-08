import { memo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

interface EditorSkeletonProps {
    /** Match the editor's computed height so the card keeps its shape when Monaco mounts. */
    height?: number | string
    /** Number of code-line rows to render. */
    lines?: number
}

const DEFAULT_LINES = 5
// Cycled, not random, so the placeholder is stable across re-renders during streaming.
const LINE_WIDTHS = ['w-3/4', 'w-1/2', 'w-5/6', 'w-2/3', 'w-11/12', 'w-1/3']

/**
 * Editor-shaped loading skeleton for the Monaco-backed tool cards (read view + diff view). A
 * `LemonSkeleton`-only leaf — no Monaco, no lazy renderers — so it's safe both as a `Suspense`
 * fallback and inside the always-loaded built-in chunk. Renders a line-number gutter column next to
 * varied-width code-line bars to read as "content loading" rather than an empty/spinning box.
 */
export const EditorSkeleton = memo(function EditorSkeleton({
    height,
    lines = DEFAULT_LINES,
}: EditorSkeletonProps): JSX.Element {
    return (
        <div
            className="flex flex-col gap-1.5 rounded border border-border-secondary px-2 py-1.5 overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={height !== undefined ? { height } : undefined}
            aria-hidden
        >
            {Array.from({ length: lines }, (_, index) => (
                <div key={index} className="flex items-center gap-2 h-[18px]">
                    <LemonSkeleton className="h-3 w-4 shrink-0 rounded-sm" />
                    <LemonSkeleton className={`h-3 rounded-sm ${LINE_WIDTHS[index % LINE_WIDTHS.length]}`} />
                </div>
            ))}
        </div>
    )
})
