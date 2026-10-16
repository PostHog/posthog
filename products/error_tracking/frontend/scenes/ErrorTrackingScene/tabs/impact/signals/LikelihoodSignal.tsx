import { Text, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { multiplier } from '../impactFormat'
import { LogRuler } from './LogRuler'
import { SignalHeadline } from './SignalHeadline'
import { useImpactPalette } from './useImpactPalette'

// A larger lift sits at the end of the scale, and the headline still shows its value.
const MAX_TIMES = 10

export interface LikelihoodSignalProps {
    rate: number
    expectedRate: number
    caption: string
    explanation: string
}

// How many times as likely something is with the error, on a log scale from the usual rate to 10 times it. A ratio
// ranks issues by severity whatever the usual rate of their pages is.
export function LikelihoodSignal({ rate, expectedRate, caption, explanation }: LikelihoodSignalProps): JSX.Element {
    const palette = useImpactPalette()
    const usualIsZero = expectedRate <= 0
    const times = usualIsZero ? MAX_TIMES : rate / expectedRate
    return (
        <Tooltip>
            <TooltipTrigger render={<div tabIndex={0} className="flex w-full max-w-64 flex-col gap-1" />}>
                <SignalHeadline
                    value={usualIsZero ? `${MAX_TIMES}×+` : multiplier(rate, expectedRate)}
                    caption={caption}
                    tone="destructive"
                />
                <LogRuler
                    min={1}
                    max={MAX_TIMES}
                    markers={[{ value: Math.min(times, MAX_TIMES), color: palette.hurting }]}
                    height={14}
                />
                <div className="flex justify-between">
                    <Text render={<span />} size="xs" variant="muted">
                        as usual
                    </Text>
                    <Text render={<span />} size="xs" variant="muted">
                        {`${MAX_TIMES}×`}
                    </Text>
                </div>
            </TooltipTrigger>
            <TooltipContent>{explanation}</TooltipContent>
        </Tooltip>
    )
}
