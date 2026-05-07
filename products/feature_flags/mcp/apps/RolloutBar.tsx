import type { ReactElement } from 'react'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill'

export interface RolloutBarProps {
    percentage: number
    tooltip?: string
    className?: string
}

export function RolloutBar({ percentage, tooltip, className }: RolloutBarProps): ReactElement {
    const clamped = Math.max(0, Math.min(100, percentage))

    const bar = (
        <div className={cn('flex items-center gap-2', className)}>
            <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${clamped}%` }} />
            </div>
            <span className="text-xs font-medium text-muted-foreground tabular-nums shrink-0">{clamped}%</span>
        </div>
    )

    if (tooltip) {
        return (
            <TooltipProvider>
                <Tooltip>
                    <TooltipTrigger render={<div className="block">{bar}</div>} />
                    <TooltipContent side="top">{tooltip}</TooltipContent>
                </Tooltip>
            </TooltipProvider>
        )
    }

    return bar
}
