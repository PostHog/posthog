import { IconTrending } from '@posthog/icons'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'

import type { KpiDelta } from './promptReport'

const VARIANTS = { up: 'success', down: 'destructive', flat: 'default' } as const
const ICONS = { up: IconTrending, down: IconTrendingDown, flat: IconTrendingFlat }

/** A change against the period before. The direction already says whether it is better, so a lower position reads as up. */
export const ContentAutopilotKpiDelta = ({ delta }: { delta: KpiDelta }): JSX.Element => {
    const Icon = ICONS[delta.direction]
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Badge
                        variant={VARIANTS[delta.direction]}
                        className="shrink-0 gap-0.5 rounded-full whitespace-nowrap tabular-nums"
                    />
                }
            >
                <Icon />
                {delta.label}
            </TooltipTrigger>
            <TooltipContent>{delta.tooltip}</TooltipContent>
        </Tooltip>
    )
}
