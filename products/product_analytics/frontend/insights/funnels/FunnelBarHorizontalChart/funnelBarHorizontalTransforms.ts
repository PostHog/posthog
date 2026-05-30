import type { Series } from 'lib/hog-charts'
import { getReferenceStep, getStepBreakdownSeries } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepReference, type FunnelStepWithConversionMetrics } from '~/types'

export const FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX = 'funnel-bar-horizontal-segment-'

const RATE_TO_PERCENT = 100

export interface FunnelBarHorizontalSegmentMeta {
    breakdownIndex: number | null
}

export interface FunnelBarHorizontalData {
    series: Series<FunnelBarHorizontalSegmentMeta>[]
    labels: string[]
}

interface BuildOptions {
    stepReference: FunnelStepReference
    breakdownFilter?: BreakdownFilter | null
    getColor: (series: FunnelStepWithConversionMetrics) => string
    getLabel: (series: FunnelStepWithConversionMetrics) => string
}

function isBreakdownLayout(steps: FunnelStepWithConversionMetrics[]): boolean {
    const first = steps[0]
    return Array.isArray(first?.nested_breakdown) && first.nested_breakdown.length > 1
}

function variantAtStep(
    step: FunnelStepWithConversionMetrics,
    breakdownIndex: number
): FunnelStepWithConversionMetrics | null {
    return step.nested_breakdown?.[breakdownIndex] ?? null
}

export function buildFunnelBarHorizontalData(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): FunnelBarHorizontalData {
    if (steps.length === 0) {
        return { series: [], labels: [] }
    }

    // Band keys must be unique — funnels often repeat the same event, so step names collide and
    // d3.scaleBand would collapse them into one band. The visible step names come from StepDecorations.
    const labels = steps.map((_, stepIndex) => String(stepIndex))

    if (isBreakdownLayout(steps)) {
        return { series: buildBreakdownSeries(steps, options), labels }
    }
    return { series: buildSingleSeries(steps, options), labels }
}

function buildBreakdownSeries(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): Series<FunnelBarHorizontalSegmentMeta>[] {
    const breakdownCount = steps[0].nested_breakdown!.length
    const series: Series<FunnelBarHorizontalSegmentMeta>[] = []

    for (let breakdownIndex = 0; breakdownIndex < breakdownCount; breakdownIndex++) {
        const fractions = steps.map((step, stepIndex) => {
            const variant = variantAtStep(step, breakdownIndex)
            if (!variant) {
                return 0
            }
            const basisCount = getReferenceStep(steps, options.stepReference, stepIndex).count
            return basisCount > 0 ? variant.count / basisCount : 0
        })
        const representative = variantAtStep(steps[0], breakdownIndex)!
        series.push({
            key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}${breakdownIndex}`,
            label: options.getLabel(representative),
            data: fractions.map((f) => f * RATE_TO_PERCENT),
            color: options.getColor(representative),
            meta: { breakdownIndex },
        })
    }

    return series
}

function buildSingleSeries(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): Series<FunnelBarHorizontalSegmentMeta>[] {
    const displaySteps = steps.map((step) => getStepBreakdownSeries(step, options.breakdownFilter) ?? step)
    const fractions = displaySteps.map((s) => s.conversionRates.fromBasisStep)
    const representative = displaySteps[0]
    const isSingleBreakdownCollapse = displaySteps[0] !== steps[0]

    const segment: Series<FunnelBarHorizontalSegmentMeta> = {
        key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}0`,
        label: options.getLabel(representative),
        data: fractions.map((f) => f * RATE_TO_PERCENT),
        color: options.getColor(representative),
        meta: { breakdownIndex: isSingleBreakdownCollapse ? 0 : null },
    }

    return [segment]
}
