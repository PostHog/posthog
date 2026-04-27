import type { ReactElement } from 'react'

import { Tooltip, cn } from '@posthog/mosaic'

export interface RolloutBarProps {
    percentage: number
    tooltip?: string
    className?: string
}

export function RolloutBar({ percentage, tooltip, className }: RolloutBarProps): ReactElement {
    const clamped = Math.max(0, Math.min(100, percentage))

    const bar = (
        <div className={cn('flex items-center gap-2', className)}>
            <div className="h-2 flex-1 rounded-full bg-bg-tertiary overflow-hidden">
                <div className="h-full rounded-full bg-info transition-all" style={{ width: `${clamped}%` }} />
            </div>
            <span className="text-xs font-medium text-text-secondary tabular-nums shrink-0">{clamped}%</span>
        </div>
    )

    if (tooltip) {
        return (
            <Tooltip content={tooltip} position="top">
                {bar}
            </Tooltip>
        )
    }

    return bar
}
