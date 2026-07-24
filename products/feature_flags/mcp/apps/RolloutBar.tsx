import type { ReactElement } from 'react'

import { cn, Progress, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@posthog/quill'

export interface RolloutBarProps {
    percentage: number
    tooltip?: string
    className?: string
}

export function RolloutBar({ percentage, tooltip, className }: RolloutBarProps): ReactElement {
    const clamped = Math.max(0, Math.min(100, percentage))

    const bar = (
        <div className={cn('flex items-center gap-2', className)}>
            <Progress value={clamped} className="flex-1" />
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
