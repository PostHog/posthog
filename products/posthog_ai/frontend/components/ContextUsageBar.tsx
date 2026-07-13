import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { runStreamLogic } from '../logics/runStreamLogic'

/** Compact SVG ring showing the context-window fill percentage. */
function UsageRing({ percentage }: { percentage: number }): JSX.Element {
    const radius = 7
    const circumference = 2 * Math.PI * radius
    const clamped = Math.max(0, Math.min(1, percentage / 100))
    return (
        <svg viewBox="0 0 18 18" className="size-4 shrink-0 -rotate-90">
            <circle cx="9" cy="9" r={radius} fill="none" strokeWidth="2.5" className="stroke-border" />
            <circle
                cx="9"
                cy="9"
                r={radius}
                fill="none"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={circumference * (1 - clamped)}
                className="stroke-accent"
            />
        </svg>
    )
}

/**
 * Context-usage indicator for sandbox conversations. Reads the latest-wins `contextUsage` snapshot
 * and renders a fill ring + `used / size · %` label when the numeric aggregate is present, plus the
 * run cost when known. Hidden when there is nothing to show. The breakdown popover is deferred.
 */
export function ContextUsageBar(): JSX.Element | null {
    const { contextUsage } = useValues(runStreamLogic)

    if (!contextUsage) {
        return null
    }

    const { used, size, cost } = contextUsage
    const hasRing = typeof used === 'number' && typeof size === 'number' && size > 0
    const percentage = hasRing ? Math.round((used! / size!) * 100) : null
    const hasCost = typeof cost === 'number'

    if (!hasRing && !hasCost) {
        return null
    }

    return (
        <div className="flex items-center gap-2 px-2 text-xs text-muted" data-attr="max-sandbox-context-usage">
            {hasRing && (
                <Tooltip title="Context window usage">
                    <span className="flex items-center gap-1.5">
                        <UsageRing percentage={percentage!} />
                        <span>
                            {humanFriendlyNumber(used!)} / {humanFriendlyNumber(size!)} · {percentage}%
                        </span>
                    </span>
                </Tooltip>
            )}
            {hasCost && <span>${cost!.toFixed(2)}</span>}
        </div>
    )
}
