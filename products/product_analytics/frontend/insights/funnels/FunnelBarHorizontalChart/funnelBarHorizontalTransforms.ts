import type { Series } from 'lib/hog-charts'
import { getReferenceStep, getStepBreakdownSeries } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepReference, type FunnelStepWithConversionMetrics } from '~/types'

export const FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX = 'funnel-bar-horizontal-segment-'
export const FUNNEL_BAR_HORIZONTAL_FILLER_KEY = 'funnel-bar-horizontal-filler'

/** Shared `bars.valueDomain` so each step's separate chart lines up (basis-step percentages, `0–100`). */
export const FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN: [number, number] = [0, 100]

const RATE_TO_PERCENT = 100

export interface FunnelBarHorizontalSegmentMeta {
    isDropOff: boolean
    breakdownIndex: number | null
}

/** Series for one step's single-band bar. Each series' `data` has exactly one value. */
export interface FunnelBarHorizontalStepData {
    /** Band label — a single per-chart slot, so just the step index as a string. */
    label: string
    series: Series<FunnelBarHorizontalSegmentMeta>[]
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
): FunnelBarHorizontalStepData[] {
    if (steps.length === 0) {
        return []
    }
    const breakdown = isBreakdownLayout(steps)
    return steps.map((step, stepIndex) => ({
        label: String(stepIndex),
        series: breakdown ? buildBreakdownSegments(steps, stepIndex, options) : buildSingleSegment(step, options),
    }))
}

function buildBreakdownSegments(
    steps: FunnelStepWithConversionMetrics[],
    stepIndex: number,
    options: BuildOptions
): Series<FunnelBarHorizontalSegmentMeta>[] {
    const step = steps[stepIndex]
    const basisCount = getReferenceStep(steps, options.stepReference, stepIndex).count
    const breakdownCount = steps[0].nested_breakdown!.length
    const segments: Series<FunnelBarHorizontalSegmentMeta>[] = []

    for (let breakdownIndex = 0; breakdownIndex < breakdownCount; breakdownIndex++) {
        const variant = variantAtStep(step, breakdownIndex)
        const fraction = variant && basisCount > 0 ? variant.count / basisCount : 0
        // Color and label come from step 0's variant so the same breakdown reads consistently
        // across steps even when a later step is missing that variant.
        const representative = variantAtStep(steps[0], breakdownIndex)!
        segments.push({
            key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}${breakdownIndex}`,
            label: options.getLabel(representative),
            data: [fraction * RATE_TO_PERCENT],
            color: options.getColor(representative),
            meta: { isDropOff: false, breakdownIndex },
        })
    }

    return [...segments, buildFiller(segments, options.fillerColor)]
}

function buildSingleSegment(
    step: FunnelStepWithConversionMetrics,
    options: BuildOptions
): Series<FunnelBarHorizontalSegmentMeta>[] {
    const displayStep = getStepBreakdownSeries(step, options.breakdownFilter) ?? step
    const isSingleBreakdownCollapse = displayStep !== step

    const segment: Series<FunnelBarHorizontalSegmentMeta> = {
        key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}0`,
        label: options.getLabel(displayStep),
        data: [displayStep.conversionRates.fromBasisStep * RATE_TO_PERCENT],
        color: options.getColor(displayStep),
        meta: { isDropOff: false, breakdownIndex: isSingleBreakdownCollapse ? 0 : null },
    }

    return [segment, buildFiller([segment], options.fillerColor)]
}

function buildFiller(
    segments: Series<FunnelBarHorizontalSegmentMeta>[],
    color: string
): Series<FunnelBarHorizontalSegmentMeta> {
    const covered = segments.reduce((sum, s) => sum + (s.data[0] ?? 0), 0)
    return {
        key: FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
        label: 'Drop-off',
        data: [Math.max(0, RATE_TO_PERCENT - covered)],
        color,
        visibility: { tooltip: false },
        meta: { isDropOff: true, breakdownIndex: null },
    }
}
