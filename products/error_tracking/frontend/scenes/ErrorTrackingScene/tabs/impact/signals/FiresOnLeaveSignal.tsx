import { Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import type { FiresOnLeaveIssue } from '../../recommendations/types'
import { multiplier, share } from '../impactFormat'
import { DotTrack } from './DotTrack'
import { SignalHeadline } from './SignalHeadline'
import { useImpactPalette } from './useImpactPalette'

// How many times more often the error lands next to a page close than a random moment does, over a dumbbell from
// the usual share to this error's share.
export function FiresOnLeaveSignal({ issue }: { issue: FiresOnLeaveIssue }): JSX.Element {
    const palette = useImpactPalette()
    return (
        <Tooltip>
            <TooltipTrigger render={<div tabIndex={0} className="flex w-full max-w-64 flex-col gap-1.5" />}>
                <SignalHeadline
                    value={multiplier(issue.leave_share, issue.baseline_leave_share)}
                    caption="more often next to a page close"
                />
                <DotTrack
                    points={[
                        { value: issue.baseline_leave_share, color: palette.ink, radius: 3.5 },
                        { value: issue.leave_share, color: palette.noise },
                    ]}
                    join={{ from: issue.baseline_leave_share, to: issue.leave_share, color: palette.noise }}
                />
            </TooltipTrigger>
            <TooltipContent>
                {`In ${share(issue.leave_share)} of sessions this error first fired between 1 second before and 2 seconds after the page closed. Around a random moment it is ${share(issue.baseline_leave_share)}, so leaving the page is likely what causes it.`}
            </TooltipContent>
        </Tooltip>
    )
}
