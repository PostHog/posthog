import type { Series, TooltipContext } from '@posthog/quill-charts'

import { getReferenceStep, getStepBreakdownSeries, hasBreakdown } from 'scenes/funnels/funnelUtils'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepReference, type FunnelStepWithConversionMetrics } from '~/types'

import {
    buildFunnelBarHorizontalDropOff,
    buildFunnelBarHorizontalFiller,
    FUNNEL_BAR_HORIZONTAL_FILLER_KEY,
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

/** One step in compare mode: two stacked bars (current, then previous) on a shared 0–100 axis.
 *  `bars[0]` is current, `bars[1]` previous; previous is omitted only when the backend sent no
 *  previous-period series for the step. A shorter period's bar sums to its own entry level, leaving
 *  the volume gap above as blank whitespace. */
export interface FunnelBarHorizontalCompareStep {
    bars: FunnelBarHorizontalStepData[]
}

/** Builds the top-to-bottom compare layout: one bar per period, per step. Each bar is scaled to the
 *  shared baseline already baked into `conversionRates.fromBasisStep` (so the larger period's first
 *  step fills the track and the other is proportional), and takes its color from the *current step's*
 *  variant — both periods share step i's color, with `getColor` dimming the `previous` series. Drop-off
 *  stops at each period's entry level (its first-step share of the shared baseline); the space above is
 *  the blank volume gap, left as whitespace rather than rendered as drop-off. */
export function buildFunnelBarHorizontalCompareData(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): FunnelBarHorizontalCompareStep[] {
    const firstNested = steps[0]?.nested_breakdown ?? []
    // Breakdown + compare draws two stacks per step (one per period), each split by breakdown value;
    // pure compare draws one bar per period. A value's series carries both a real breakdown value and a
    // compare label, whereas pure compare carries only the label.
    if (firstNested.some((variant) => variant.compare_label != null && hasBreakdown(variant.breakdown_value))) {
        return buildBreakdownCompareStacks(steps, options)
    }

    // Each period's entry level on the shared axis, indexed to match nested_breakdown order.
    const entryLevels = firstNested.map((variant) => variant.conversionRates.fromBasisStep * RATE_TO_PERCENT)
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
                series: [
                    segment,
                    buildFunnelBarHorizontalDropOff(
                        [segment],
                        entryLevels[breakdownIndex] ?? 0,
                        options.fillerColor,
                        breakdownIndex
                    ),
                ],
            }
        })
        return { bars }
    })
}

export interface FunnelBarHorizontalHoverTarget {
    /** The breakdown variant (or the whole step) the tooltip should describe. */
    series: FunnelStepWithConversionMetrics
    /** True when the cursor is over the drop-off filler rather than a converted segment. */
    isDropOffHover: boolean
    /** Swatch color for the tooltip header; unset for whole-step drop-off. */
    color?: string
}

type FunnelBarHorizontalHoverContext = Pick<
    TooltipContext<FunnelBarHorizontalSegmentMeta>,
    'hoveredSeriesKey' | 'seriesData' | 'hoverPosition'
>

/** Resolves which breakdown variant a hover maps to. `hoveredSeriesKey` identifies the exact
 *  stacked segment under the cursor (including the tooltip-hidden drop-off filler) — without it,
 *  `seriesData` lists every breakdown segment in declaration order and index 0 is just the first
 *  breakdown, not the hovered one. Returns `null` when there is nothing to describe. */
export function resolveFunnelBarHorizontalHover(
    context: FunnelBarHorizontalHoverContext,
    step: FunnelStepWithConversionMetrics,
    stepIndex: number
): FunnelBarHorizontalHoverTarget | null {
    const { hoveredSeriesKey, seriesData } = context
    const variantAt = (breakdownIndex: number | null | undefined): FunnelStepWithConversionMetrics =>
        breakdownIndex != null && step.nested_breakdown?.[breakdownIndex] ? step.nested_breakdown[breakdownIndex] : step

    if (hoveredSeriesKey === FUNNEL_BAR_HORIZONTAL_FILLER_KEY) {
        // Drop-off region. A lone visible segment (compare bar, plain funnel) shares the filler's
        // variant, so resolve from it; multiple segments (breakdown) means the whole step's drop-off.
        // The aggregate step inherits `breakdown_value` from its first variant (aggregateBreakdownResult
        // spreads it), so clear it — the whole step's drop-off is not one breakdown's.
        const entry = seriesData.length === 1 ? seriesData[0] : undefined
        return {
            series: entry
                ? variantAt(entry.series.meta?.breakdownIndex)
                : { ...step, breakdown: undefined, breakdown_value: undefined },
            isDropOffHover: stepIndex > 0,
            color: entry?.color,
        }
    }

    const hoveredEntry =
        hoveredSeriesKey != null ? seriesData.find((entry) => entry.series.key === hoveredSeriesKey) : undefined
    if (hoveredEntry) {
        return {
            series: variantAt(hoveredEntry.series.meta?.breakdownIndex),
            isDropOffHover: false,
            color: hoveredEntry.color,
        }
    }

    // No hovered identity (e.g. a pinned rebuild without a cursor): fall back to the first segment,
    // inferring drop-off from the cursor sitting past the segment's value-axis end pixel.
    const entry = seriesData[0]
    if (!entry) {
        return null
    }
    const isDropOffHover =
        stepIndex > 0 && context.hoverPosition != null && entry.yPixel != null && context.hoverPosition.x > entry.yPixel
    return { series: variantAt(entry.series.meta?.breakdownIndex), isDropOffHover, color: entry.color }
}

/** Builds the breakdown + compare layout: two stacks per step (current, then previous), each split into
 *  breakdown-value segments and scaled to whichever period had more total entrants at the first step. The
 *  smaller period's stack is shorter, its volume gap left blank. The aggregate drop-off band spans all
 *  values for the period, so it's tagged `breakdownIndex: null` — the chart leaves it non-clickable. */
function buildBreakdownCompareStacks(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): FunnelBarHorizontalCompareStep[] {
    const firstStep = periodTotals(steps[0])
    // Both stacks share the larger period's first-step total, so the smaller stack sits proportionally short.
    const basis = Math.max(firstStep.current, firstStep.previous, 0)
    const toPercent = (count: number): number => (basis > 0 ? (count / basis) * RATE_TO_PERCENT : 0)
    const currentEntry = toPercent(firstStep.current)
    const previousEntry = toPercent(firstStep.previous)

    return steps.map((step, stepIndex) => {
        const current: Series<FunnelBarHorizontalSegmentMeta>[] = []
        const previous: Series<FunnelBarHorizontalSegmentMeta>[] = []
        ;(step.nested_breakdown ?? []).forEach((variant, breakdownIndex) => {
            const segment: Series<FunnelBarHorizontalSegmentMeta> = {
                key: `${FUNNEL_BAR_HORIZONTAL_SEGMENT_KEY_PREFIX}${breakdownIndex}`,
                label: options.getLabel(variant),
                data: [toPercent(variant.count)],
                color: options.getColor(variant),
                meta: { isDropOff: false, breakdownIndex },
            }
            ;(variant.compare_label === 'previous' ? previous : current).push(segment)
        })
        return {
            bars: [
                {
                    label: String(stepIndex),
                    series: [...current, buildFunnelBarHorizontalDropOff(current, currentEntry, options.fillerColor)],
                },
                {
                    label: String(stepIndex),
                    series: [
                        ...previous,
                        buildFunnelBarHorizontalDropOff(previous, previousEntry, options.fillerColor),
                    ],
                },
            ],
        }
    })
}

/** Sums a period's first-step counts split by compare label — the basis for the shared stack scale. */
function periodTotals(step: FunnelStepWithConversionMetrics | undefined): { current: number; previous: number } {
    let current = 0
    let previous = 0
    for (const variant of step?.nested_breakdown ?? []) {
        if (variant.compare_label === 'previous') {
            previous += variant.count
        } else {
            current += variant.count
        }
    }
    return { current, previous }
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
