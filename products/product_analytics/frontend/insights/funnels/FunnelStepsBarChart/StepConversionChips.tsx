/* eslint-disable react/forbid-dom-props -- positions come from the chart scales */
import { useMemo } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { RATE_TO_PERCENT, useChartLayout } from '@posthog/quill-charts'

import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'

import type { FunnelStepWithConversionMetrics } from '~/types'

import { placeStepConversionChips, type StepBandBox } from './funnelStepsBarTransforms'

// Keeps the chip inside the plot when the previous bar is at 100% or close to zero.
const CHIP_TOP_INSET_PX = 12
const CHIP_BOTTOM_INSET_PX = 40

interface StepConversionChipsProps {
    steps: FunnelStepWithConversionMetrics[]
}

export function StepConversionChips({ steps }: StepConversionChipsProps): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()

    const placements = useMemo(() => {
        const bands: StepBandBox[] = labels.map((label) => {
            const center = scales.x(label) ?? 0
            const width = scales.extent?.(label) ?? 0
            return { left: center - width / 2, width }
        })
        return placeStepConversionChips(bands.slice(0, steps.length))
    }, [scales.x, scales.extent, labels, steps.length])

    if (placements.length === 0) {
        return null
    }

    const minTop = dimensions.plotTop + CHIP_TOP_INSET_PX
    const maxTop = dimensions.plotTop + dimensions.plotHeight - CHIP_BOTTOM_INSET_PX

    return (
        <>
            {placements.map(({ stepIndex, centerX }) => {
                const step = steps[stepIndex]
                const previousStep = steps[stepIndex - 1]
                if (!step || !previousStep) {
                    return null
                }
                // Anchor at the top of the previous bar, so the chip reads as the step down to the next bar.
                const previousBarTop = scales.y(previousStep.conversionRates.fromBasisStep * RATE_TO_PERCENT)
                const top = Math.min(maxTop, Math.max(minTop, previousBarTop))
                return (
                    <div
                        key={stepIndex}
                        className="pointer-events-none absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-0.5"
                        style={{ left: centerX, top }}
                        data-attr="funnel-step-conversion-chip"
                        translate="no"
                    >
                        <span className="flex items-center gap-0.5 rounded-full border border-primary bg-surface-primary px-1.5 text-xs font-semibold leading-5 tabular-nums">
                            <IconArrowRight className="shrink-0 text-secondary" />
                            <span>{percentage(step.conversionRates.fromPrevious, 0)}</span>
                        </span>
                        {step.droppedOffFromPrevious > 0 && (
                            <span className="text-xs font-semibold text-danger tabular-nums">
                                {`−${humanFriendlyLargeNumber(step.droppedOffFromPrevious)}`}
                            </span>
                        )}
                    </div>
                )
            })}
        </>
    )
}
