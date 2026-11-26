import { Progress, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { percentage } from 'lib/utils/numbers'

/** A share as a bar on a 0 to 100% track, with the percentage beside it. The base goes in the tooltip, never the cell. */
export const ContentAutopilotRateBar = ({ rate, tooltip }: { rate: number | null; tooltip?: string }): JSX.Element => {
    if (rate === null) {
        return <span className="block text-right text-muted-foreground">-</span>
    }
    const value = Math.max(0, Math.min(100, rate * 100))
    const label = percentage(rate, 0)
    const bar = (
        // Reversed, so the percentage that Progress draws before its track sits after it.
        <Progress
            value={value}
            aria-label={label}
            className="w-full min-w-24 flex-row-reverse flex-nowrap items-center gap-2"
        >
            <span className="w-10 shrink-0 text-right tabular-nums">{label}</span>
        </Progress>
    )
    return tooltip ? (
        <Tooltip>
            <TooltipTrigger render={<span className="block w-full" />}>{bar}</TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    ) : (
        bar
    )
}
