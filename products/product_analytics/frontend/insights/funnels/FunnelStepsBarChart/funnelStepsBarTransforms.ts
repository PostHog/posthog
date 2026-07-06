import type { BarChartConfig, PointClickData } from '@posthog/quill-charts'

import { getVisibilityKey } from 'scenes/funnels/funnelUtils'

import type { BreakdownKeyType, FunnelStepWithConversionMetrics } from '~/types'

import { INSIGHT_TOOLTIP_CONFIG } from '../../shared/tooltipConfig'
import { RATE_TO_PERCENT } from '../shared/funnelBarHorizontalShared'
import {
    buildFunnelStepsBars,
    type FunnelStepsBarsModel,
    type FunnelStepsBarVariant,
} from '../shared/funnelStepsBarShared'

export const FUNNEL_STEPS_SERIES_KEY_PREFIX = 'funnel-step-series-'

/** Identifies which breakdown variant a hog-charts series maps back to, so click and
 *  tooltip handlers can recover the original `FunnelStepWithConversionMetrics`. `breakdownIndex` is
 *  the original nested-array index even when compare reorders the visual series, so click/tooltip
 *  routing stays correct; `compareLabel`/`breakdownValue` describe the series for ordering and tests. */
export interface FunnelStepsBarSeriesMeta {
    breakdownIndex: number
    compareLabel?: 'current' | 'previous'
    breakdownValue?: BreakdownKeyType
}

interface BuildOptions {
    getColor: (series: FunnelStepWithConversionMetrics) => string
    getLabel: (series: FunnelStepWithConversionMetrics) => string
}

export type FunnelStepsBarData = FunnelStepsBarsModel<FunnelStepsBarSeriesMeta>

function variantAtStep(
    step: FunnelStepWithConversionMetrics,
    breakdownIndex: number,
    isBreakdown: boolean
): FunnelStepWithConversionMetrics {
    if (!isBreakdown) {
        return step
    }
    const variant = step.nested_breakdown?.[breakdownIndex]
    if (variant) {
        return variant
    }
    // The breakdown variant is absent for this step — treat as no conversion rather than
    // inflating to the parent step's aggregate rate.
    return { ...step, conversionRates: { ...step.conversionRates, fromBasisStep: 0 } }
}

/** Maps the funnel steps onto grouped hog-charts bar series — one series per breakdown
 *  variant, one bar per step, valued by conversion rate from the basis step. Resolves the
 *  breakdown variants (web-only) and defers to the shared builder for the band labels, rows,
 *  and overall stats it shares with the MCP funnel app. */
export function buildFunnelStepsBarData(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): FunnelStepsBarData {
    if (steps.length === 0) {
        return buildFunnelStepsBars<FunnelStepsBarSeriesMeta>([], [])
    }

    const isBreakdown = steps[0].nested_breakdown != null
    const breakdownCount = isBreakdown ? steps[0].nested_breakdown!.length : 1
    const isCompare = steps[0].nested_breakdown?.some((variant) => variant.compare_label != null) ?? false
    const seriesVariants: FunnelStepsBarVariant<FunnelStepsBarSeriesMeta>[] = []

    for (let breakdownIndex = 0; breakdownIndex < breakdownCount; breakdownIndex++) {
        const variants = steps.map((step) => variantAtStep(step, breakdownIndex, isBreakdown))
        const representative = variants[0]
        // A period's entry level (its share of the larger baseline, shared by all its values) is constant
        // across steps; it caps the drop-off track so the volume gap above is blank. Compare mode only.
        const entryLevel = (representative?.conversionRates.fromBasisStep ?? 0) * RATE_TO_PERCENT
        seriesVariants.push({
            key: `${FUNNEL_STEPS_SERIES_KEY_PREFIX}${breakdownIndex}`,
            label: representative ? options.getLabel(representative) : '',
            data: variants.map((variant) => variant.conversionRates.fromBasisStep * RATE_TO_PERCENT),
            color: representative ? options.getColor(representative) : undefined,
            meta: {
                breakdownIndex,
                compareLabel: representative?.compare_label,
                breakdownValue: representative?.breakdown_value,
            },
            ...(isCompare ? { trackData: steps.map(() => entryLevel) } : {}),
        })
    }

    // Grouped-bar slots render in series-array order, so reorder (not relabel) to put each value's
    // previous-period bar left of its current one. Each series keeps its original breakdownIndex, so
    // `resolveFunnelStepClick` and the tooltip still recover the right variant after the swap.
    return buildFunnelStepsBars(steps, isCompare ? orderCompareSeriesPreviousFirst(seriesVariants) : seriesVariants)
}

/** Reorders compare series so each breakdown value's previous-period bar precedes its current one,
 *  preserving the values' incoming order. Pure compare has a single value, so it just swaps the
 *  current/previous pair. */
function orderCompareSeriesPreviousFirst(
    series: FunnelStepsBarVariant<FunnelStepsBarSeriesMeta>[]
): FunnelStepsBarVariant<FunnelStepsBarSeriesMeta>[] {
    const valueOrder: string[] = []
    const byValue = new Map<string, FunnelStepsBarVariant<FunnelStepsBarSeriesMeta>[]>()
    for (const variant of series) {
        const key = getVisibilityKey(variant.meta?.breakdownValue)
        if (!byValue.has(key)) {
            byValue.set(key, [])
            valueOrder.push(key)
        }
        byValue.get(key)!.push(variant)
    }
    return valueOrder.flatMap((key) =>
        [...byValue.get(key)!].sort(
            (a, b) => Number(a.meta?.compareLabel === 'current') - Number(b.meta?.compareLabel === 'current')
        )
    )
}

/** Derives the chart config from the base config plus whether the new pinnable tooltip is
 *  enabled. A breakdown always puts one series per breakdown value at each step, so a pinnable
 *  tooltip here always covers multiple series — `resolveClickToNearestSeries` resolves the
 *  click to the nearest one and opens its persons modal directly instead of pinning first. */
export function withFunnelStepsBarInteraction(
    baseConfig: BarChartConfig,
    options: { quillTooltipEnabled: boolean }
): BarChartConfig {
    if (options.quillTooltipEnabled) {
        return {
            ...baseConfig,
            tooltip: { ...INSIGHT_TOOLTIP_CONFIG, resolveClickToNearestSeries: true },
        }
    }
    return baseConfig
}

export interface FunnelStepClickTarget {
    step: FunnelStepWithConversionMetrics
    series: FunnelStepWithConversionMetrics
    converted: boolean
}

/** Resolves a grouped-bar click back to the funnel step, breakdown variant, and whether the
 *  converted or drop-off actors should open. The bar's filled extent is the converted portion;
 *  the track above it (`inTrackArea`) is the drop-off — restoring the legacy StepBar behavior.
 *  Returns `null` when the click does not map to a step. */
export function resolveFunnelStepClick(
    steps: FunnelStepWithConversionMetrics[],
    clickData: Pick<PointClickData<FunnelStepsBarSeriesMeta>, 'dataIndex' | 'series' | 'inTrackArea'>
): FunnelStepClickTarget | null {
    const step = steps[clickData.dataIndex]
    if (!step) {
        return null
    }
    const breakdownIndex = clickData.series.meta?.breakdownIndex ?? 0
    const variant = step.nested_breakdown?.[breakdownIndex] ?? step
    return { step, series: variant, converted: !clickData.inTrackArea }
}
