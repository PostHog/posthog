import type { Series } from '@posthog/quill-charts'

import { getReferenceStep, getStepBreakdownSeries, hasBreakdown } from 'scenes/funnels/funnelUtils'

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

/** One step in compare mode: a current bar then a previous bar, stacked top-to-bottom in the DOM
 *  (`bars[0]` current, `bars[1]` previous). Each "bar" is a single-segment track in pure compare, or a
 *  breakdown-value stack in breakdown × compare. A period is omitted only when the backend sent no
 *  series for it. */
export interface FunnelBarHorizontalCompareStep {
    bars: FunnelBarHorizontalStepData[]
}

const COMPARE_PERIODS = ['current', 'previous'] as const

/** Top-to-bottom compare layout.
 *
 *  Pure compare → one single-segment bar per period (current then previous), each scaled to the shared
 *  baseline baked into `conversionRates.fromBasisStep` and capped at its own entry so the headroom is
 *  empty. Colors come from each step's own variant, with `getColor` dimming the `previous` series.
 *
 *  Breakdown × compare → two *stacked* bars per step (current then previous), composed by breakdown
 *  value — see {@link buildBreakdownCompareStacks}. */
export function buildFunnelBarHorizontalCompareData(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): FunnelBarHorizontalCompareStep[] {
    const firstNested = steps[0]?.nested_breakdown ?? []
    if (firstNested.some((variant) => hasBreakdown(variant.breakdown_value))) {
        return buildBreakdownCompareStacks(steps, firstNested, options)
    }
    return steps.map((step, stepIndex) => {
        const bars = (step.nested_breakdown ?? []).map((variant, breakdownIndex) => {
            const segment: Series<FunnelBarHorizontalSegmentMeta> = {
                key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}${breakdownIndex}`,
                label: options.getLabel(variant),
                data: [variant.conversionRates.fromBasisStep * RATE_TO_PERCENT],
                color: options.getColor(variant),
                meta: { isDropOff: false, breakdownIndex },
            }
            // Cap the drop-off filler at this period's own entry level (its step-0 fraction of the
            // shared baseline) so only genuine within-period drop-off shows; the bar then stops at the
            // cap, leaving the headroom up to 100% empty and inert.
            const capPercent =
                (steps[0].nested_breakdown?.[breakdownIndex]?.conversionRates.fromBasisStep ?? 1) * RATE_TO_PERCENT
            const dropOff = buildFunnelBarHorizontalFiller([segment], options.fillerColor, breakdownIndex, capPercent)
            return {
                label: String(stepIndex),
                series: [segment, dropOff],
            }
        })
        return { bars }
    })
}

/** Breakdown × compare: a current stack and a previous stack per step, each composed of one segment
 *  per breakdown value (the same per-value colors the non-compare breakdown stack uses, with the
 *  previous stack dimmed). Both stacks share the larger period's first-step total as the baseline, so
 *  the shorter period's stack is proportionally shorter with empty, inert headroom above; each stack's
 *  drop-off filler caps at that period's own entry. Segments carry their `nested_breakdown` index so a
 *  click opens that (value, period); the per-period aggregate drop-off filler has no single series, so
 *  it's tagged `breakdownIndex: null` and the chart leaves it inert. */
function buildBreakdownCompareStacks(
    steps: FunnelStepWithConversionMetrics[],
    firstNested: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): FunnelBarHorizontalCompareStep[] {
    const periodEntries = COMPARE_PERIODS.map((period) =>
        firstNested
            .map((representative, index) => ({ representative, index }))
            .filter((entry) => entry.representative.compare_label === period)
    )
    const periodTotals = periodEntries.map((entries) =>
        entries.reduce((sum, entry) => sum + entry.representative.count, 0)
    )
    const basis = Math.max(...periodTotals, 0)
    const toPercent = (count: number): number => (basis > 0 ? (count / basis) * RATE_TO_PERCENT : 0)

    return steps.map((step, stepIndex) => {
        const bars = periodEntries
            .map((entries, periodIndex) => ({ entries, cap: toPercent(periodTotals[periodIndex]) }))
            .filter(({ entries }) => entries.length > 0)
            .map(({ entries, cap }) => {
                const segments: Series<FunnelBarHorizontalSegmentMeta>[] = entries.map(({ representative, index }) => ({
                    key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}${index}`,
                    label: options.getLabel(representative),
                    data: [toPercent(step.nested_breakdown?.[index]?.count ?? 0)],
                    color: options.getColor(representative),
                    meta: { isDropOff: false, breakdownIndex: index },
                }))
                const dropOff = buildFunnelBarHorizontalFiller(segments, options.fillerColor, null, cap)
                return { label: String(stepIndex), series: [...segments, dropOff] }
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
