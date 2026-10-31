/* eslint-disable react/forbid-dom-props -- positions come from the chart scales */
import { useMemo } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { RATE_TO_PERCENT, useChartLayout } from '@posthog/quill-charts'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { FunnelStepWithConversionMetrics } from '~/types'

import { formatFunnelStepRate, placeStepConversionChips, type StepBandBox } from './funnelStepsBarTransforms'

const CHIP_ROW_HEIGHT_PX = 16
const CHIP_CHROME_PX = 6
const CHIP_EDGE_INSET_PX = 4

interface StepConversionChipsProps {
    steps: FunnelStepWithConversionMetrics[]
    stepIndexes: number[]
}

export function StepConversionChips({ steps, stepIndexes }: StepConversionChipsProps): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()

    const placements = useMemo(() => {
        const bands: StepBandBox[] = labels.map((label) => {
            const center = scales.x(label) ?? 0
            const width = scales.extent?.(label) ?? 0
            return { left: center - width / 2, width }
        })
        return placeStepConversionChips(bands.slice(0, steps.length)).filter(({ stepIndex }) =>
            stepIndexes.includes(stepIndex)
        )
    }, [scales, labels, steps.length, stepIndexes])

    if (placements.length === 0) {
        return null
    }

    const plotBottom = dimensions.plotTop + dimensions.plotHeight

    return (
        <>
            {placements.map(({ stepIndex, centerX }) => {
                const step = steps[stepIndex]
                const previousStep = steps[stepIndex - 1]
                if (!step || !previousStep) {
                    return null
                }
                const hasDropOff = step.droppedOffFromPrevious > 0
                const chipHeight = (hasDropOff ? 2 : 1) * CHIP_ROW_HEIGHT_PX + CHIP_CHROME_PX
                // Centers the rate row on the previous bar's top, so chips line up whether or not they show a drop-off.
                const previousBarTop = scales.y(previousStep.conversionRates.fromBasisStep * RATE_TO_PERCENT)
                const top = Math.min(
                    plotBottom - chipHeight - CHIP_EDGE_INSET_PX,
                    Math.max(
                        dimensions.plotTop + CHIP_EDGE_INSET_PX,
                        previousBarTop - (CHIP_ROW_HEIGHT_PX + CHIP_CHROME_PX) / 2
                    )
                )
                return (
                    <div
                        key={stepIndex}
                        className="pointer-events-none absolute flex -translate-x-1/2 flex-col items-center rounded-md border border-primary bg-surface-primary px-1 py-0.5 text-xs leading-4 tabular-nums shadow-sm"
                        style={{ left: centerX, top }}
                        data-attr="funnel-step-conversion-chip"
                        translate="no"
                    >
                        <span className="flex items-center gap-0.5 font-semibold">
                            <IconArrowRight className="size-3 shrink-0 text-secondary" />
                            {formatFunnelStepRate(step.conversionRates.fromPrevious)}
                        </span>
                        {hasDropOff && (
                            <span className="text-danger">{`−${humanFriendlyLargeNumber(step.droppedOffFromPrevious)}`}</span>
                        )}
                    </div>
                )
            })}
        </>
    )
}
