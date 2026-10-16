import { Text, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { SupportTicketsIssue } from '../../recommendations/types'
import { multiplier } from '../impactFormat'
import { SignalHeadline } from './SignalHeadline'
import { UnitGrid } from './UnitGrid'
import { useImpactPalette } from './useImpactPalette'

const MAX_UNITS = 24

const oneIn = (per1k: number): number => Math.max(Math.round(1000 / Math.max(per1k, 0.001)), 1)

// The ticket rate as a frequency: 1 in N sessions with this error opened a ticket. The dot row makes N physical.
export function SupportTicketsSignal({
    issue,
    baselinePer1k,
}: {
    issue: SupportTicketsIssue
    baselinePer1k: number
}): JSX.Element {
    const palette = useImpactPalette()
    const n = oneIn(issue.per_1k)
    return (
        <Tooltip>
            <TooltipTrigger render={<div tabIndex={0} className="flex w-full max-w-64 flex-col gap-1.5" />}>
                <SignalHeadline
                    value={`1 in ${humanFriendlyLargeNumber(n)}`}
                    caption="sessions opened a ticket"
                    tone="destructive"
                />
                <div className="flex items-center gap-1.5">
                    <UnitGrid
                        total={Math.min(n, MAX_UNITS)}
                        filled={1}
                        columns={MAX_UNITS}
                        color={palette.hurting}
                        size={6}
                        gap={2}
                        shape="circle"
                    />
                    {n > MAX_UNITS && (
                        <Text render={<span />} size="xs" variant="muted" className="tabular-nums">
                            {`+${humanFriendlyLargeNumber(n - MAX_UNITS)}`}
                        </Text>
                    )}
                </div>
                <Text size="xs" variant="muted" className="tabular-nums">
                    {`Usually 1 in ${humanFriendlyLargeNumber(oneIn(baselinePer1k))}`}
                </Text>
            </TooltipTrigger>
            <TooltipContent>
                {`${issue.tickets} tickets were opened within 5 minutes after this error, ${multiplier(issue.per_1k, baselinePer1k)} your usual rate of tickets per session.`}
            </TooltipContent>
        </Tooltip>
    )
}
