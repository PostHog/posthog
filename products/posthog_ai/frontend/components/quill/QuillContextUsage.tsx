import { useValues } from 'kea'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { runStreamLogic } from '../../logics/runStreamLogic'

const RING_RADIUS = 5.5
const RING_LENGTH = 2 * Math.PI * RING_RADIUS

export function QuillContextUsage(): JSX.Element | null {
    const { contextUsage } = useValues(runStreamLogic)
    const used = contextUsage?.used
    const size = contextUsage?.size
    const hasRing = typeof used === 'number' && typeof size === 'number' && size > 0
    const cost = typeof contextUsage?.cost === 'number' ? contextUsage.cost : null
    if (!hasRing && cost === null) {
        return null
    }
    const percentage = hasRing ? Math.min(100, Math.round((used / size) * 100)) : null
    const tone =
        percentage !== null && percentage >= 95
            ? 'text-destructive-foreground'
            : percentage !== null && percentage >= 80
              ? 'text-warning-foreground'
              : 'text-muted-foreground'
    const details = [
        hasRing
            ? `Context ${percentage}% full, ${humanFriendlyNumber(used)} of ${humanFriendlyNumber(size)} tokens`
            : null,
        cost !== null ? `$${cost.toFixed(2)} spent in this chat` : null,
    ].filter(Boolean)

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        tabIndex={0}
                        className={cn(
                            'flex items-center gap-1 text-xs tabular-nums whitespace-nowrap text-muted-foreground',
                            (percentage === null || percentage < 80) && '@max-[359px]/composer:hidden'
                        )}
                        data-attr="max-sandbox-context-usage"
                    >
                        {percentage !== null && (
                            <svg viewBox="0 0 14 14" className={cn('size-3.5 shrink-0 -rotate-90', tone)} aria-hidden>
                                <circle
                                    cx="7"
                                    cy="7"
                                    r={RING_RADIUS}
                                    fill="none"
                                    stroke="currentColor"
                                    strokeOpacity={0.2}
                                    strokeWidth={2}
                                />
                                <circle
                                    cx="7"
                                    cy="7"
                                    r={RING_RADIUS}
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth={2}
                                    strokeLinecap="round"
                                    strokeDasharray={RING_LENGTH}
                                    strokeDashoffset={RING_LENGTH * (1 - percentage / 100)}
                                />
                            </svg>
                        )}
                        {percentage !== null && percentage >= 80 && <span className={tone}>{percentage}%</span>}
                        {cost !== null && <span className="@max-[480px]/composer:hidden">${cost.toFixed(2)}</span>}
                    </span>
                }
            />
            <TooltipContent>{details.join('. ')}</TooltipContent>
        </Tooltip>
    )
}
