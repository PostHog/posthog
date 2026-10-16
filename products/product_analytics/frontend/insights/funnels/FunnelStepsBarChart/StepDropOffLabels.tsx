import { useChartLayout } from '@posthog/quill-charts'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { FunnelStepWithConversionMetrics } from '~/types'

import { RATE_TO_PERCENT } from '../shared/funnelBarHorizontalShared'

// Room for this label plus the conversion label on the bar tip, so the two never overlap.
const MIN_TRACK_HEIGHT_PX = 44

export function StepDropOffLabels({ steps }: { steps: FunnelStepWithConversionMetrics[] }): JSX.Element {
    const { scales, labels } = useChartLayout()
    const trackTop = scales.y(RATE_TO_PERCENT)

    return (
        <>
            {steps.map((step, stepIndex) => {
                const x = scales.x(labels[stepIndex])
                const barTop = scales.y(step.conversionRates.fromBasisStep * RATE_TO_PERCENT)
                if (x == null || !step.droppedOffFromPrevious || barTop - trackTop < MIN_TRACK_HEIGHT_PX) {
                    return null
                }
                return (
                    <div
                        key={stepIndex}
                        className="absolute -translate-x-1/2 whitespace-nowrap rounded bg-surface-primary px-1 text-xs text-secondary"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: x, top: trackTop + 4 }}
                        data-attr="funnel-step-dropped-off-label"
                    >
                        {humanFriendlyNumber(step.droppedOffFromPrevious)} dropped off
                    </div>
                )
            })}
        </>
    )
}
