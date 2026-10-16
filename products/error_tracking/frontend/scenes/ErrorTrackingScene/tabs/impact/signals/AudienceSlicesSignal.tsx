import { Text, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import type { AudienceSliceIssue } from '../../recommendations/types'
import { AUDIENCE_DIMENSION_LABELS, share, sliceLabel } from '../impactFormat'
import { ShareBar } from './ShareBar'
import { useImpactPalette } from './useImpactPalette'

// Bullet bars: the bar is the share of the issue's sessions, the tick is the same value's share of your traffic.
export function AudienceSlicesSignal({ issue }: { issue: AudienceSliceIssue }): JSX.Element {
    const palette = useImpactPalette()
    return (
        <div className="flex w-full max-w-64 flex-col gap-2">
            {issue.slices.map((slice) => {
                const label = sliceLabel(slice)
                return (
                    <Tooltip key={`${slice.dimension}-${slice.value}`}>
                        <TooltipTrigger
                            render={
                                <div
                                    tabIndex={0}
                                    className="grid grid-cols-[minmax(0,6.5rem)_minmax(0,1fr)_2.5rem] items-center gap-2"
                                />
                            }
                        >
                            <Text render={<span />} size="xs" weight="medium" className="truncate">
                                {label}
                            </Text>
                            <ShareBar
                                value={slice.issue_share}
                                marker={slice.baseline_share}
                                color={palette.audience}
                            />
                            <Text render={<span />} size="xs" weight="semibold" className="text-right tabular-nums">
                                {share(slice.issue_share)}
                            </Text>
                        </TooltipTrigger>
                        <TooltipContent>
                            {`${share(slice.issue_share)} of this issue's sessions have ${label} as their ${AUDIENCE_DIMENSION_LABELS[slice.dimension]}, compared with ${share(slice.baseline_share)} of your traffic.`}
                        </TooltipContent>
                    </Tooltip>
                )
            })}
        </div>
    )
}
