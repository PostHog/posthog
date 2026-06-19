import type { Series } from '@posthog/quill-charts'

import { getReferenceStep, getStepBreakdownSeries } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepReference, type FunnelStepWithConversionMetrics } from '~/types'

import {
    buildFunnelBarHorizontalFiller,
    FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX,
    RATE_TO_PERCENT,
    type FunnelBarHorizontalSegmentMeta,
    type FunnelBarHorizontalStepData,
} from '../shared/funnelBarHorizontalShared'

// Re-exported so existing importers (the chart component, tests) keep a single entry point even
// though the neutral primitives now live in the shared module for the MCP bundle to reuse.
export {
    FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
    FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX,
    FUNNEL_BAR_HORIZONTAL_VALUE_DOMAIN,
    type FunnelBarHorizontalSegmentMeta,
    type FunnelBarHorizontalStepData,
} from '../shared/funnelBarHorizontalShared'

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

    return [...segments, buildFunnelBarHorizontalFiller(segments, options.fillerColor)]
}

/** One step in compare mode: two stacked bars (current, then previous), each a full 0–100 track
 *  rather than two segments sharing one track. `bars[0]` is current, `bars[1]` previous; previous is
 *  omitted only when the backend sent no previous-period series for the step. */
export interface FunnelBarHorizontalCompareStep {
    bars: FunnelBarHorizontalStepData[]
}

/** Builds the top-to-bottom compare layout: one bar per period, per step. Each bar is scaled to the
 *  shared baseline already baked into `conversionRates.fromBasisStep` (so the larger period's first
 *  step fills the track and the other is proportional), and takes its color from the *current step's*
 *  variant — both periods share step i's color, with `getColor` dimming the `previous` series. This is
 *  the key difference from `buildBreakdownSegments`, whose representative comes from step 0. */
export function buildFunnelBarHorizontalCompareData(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): FunnelBarHorizontalCompareStep[] {
    return steps.map((step, stepIndex) => {
        const bars = (step.nested_breakdown ?? []).map((variant, breakdownIndex) => {
            const segment: Series<FunnelBarHorizontalSegmentMeta> = {
                key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}${breakdownIndex}`,
                label: options.getLabel(variant),
                data: [variant.conversionRates.fromBasisStep * RATE_TO_PERCENT],
                color: options.getColor(variant),
                meta: { isDropOff: false, breakdownIndex },
            }
            return {
                label: String(stepIndex),
                series: [segment, buildFunnelBarHorizontalFiller([segment], options.fillerColor, breakdownIndex)],
            }
        })
        return { bars }
    })
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

    return [segment, buildFunnelBarHorizontalFiller([segment], options.fillerColor)]
}
