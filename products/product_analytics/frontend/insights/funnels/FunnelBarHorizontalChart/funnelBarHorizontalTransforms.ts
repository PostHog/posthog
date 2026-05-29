import type { Series } from 'lib/hog-charts'
import { getReferenceStep, getStepBreakdownSeries } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepReference, type FunnelStepWithConversionMetrics } from '~/types'

export const FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX = 'funnel-bar-horizontal-segment-'
export const FUNNEL_BAR_HORIZONTAL_FILLER_KEY = 'funnel-bar-horizontal-filler'

const RATE_TO_PERCENT = 100

export interface FunnelBarHorizontalSegmentMeta {
    isDropOff: boolean
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
    fillerColor: string
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

    const labels = steps.map((step) => step.name)

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
            meta: { isDropOff: false, breakdownIndex },
        })
    }

    series.push(buildFiller(steps, series, options.fillerColor))
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
        meta: { isDropOff: false, breakdownIndex: isSingleBreakdownCollapse ? 0 : null },
    }

    return [segment, buildFiller(steps, [segment], options.fillerColor)]
}

function buildFiller(
    steps: FunnelStepWithConversionMetrics[],
    segments: Series<FunnelBarHorizontalSegmentMeta>[],
    color: string
): Series<FunnelBarHorizontalSegmentMeta> {
    const fillerData = steps.map((_, stepIndex) => {
        const covered = segments.reduce((sum, s) => sum + (s.data[stepIndex] ?? 0), 0)
        return Math.max(0, RATE_TO_PERCENT - covered)
    })
    return {
        key: FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
        label: 'Drop-off',
        data: fillerData,
        color,
        visibility: { tooltip: false },
        meta: { isDropOff: true, breakdownIndex: null },
    }
}
