import type { BarChartConfig, PointClickData } from '@posthog/quill-charts'

import type { FunnelStepWithConversionMetrics } from '~/types'

import { INSIGHT_TOOLTIP_CONFIG } from '../../shared/tooltipConfig'
import { RATE_TO_PERCENT } from '../shared/funnelBarHorizontalShared'
import {
    buildFunnelStepsBars,
    type FunnelStepsBarsModel,
    type FunnelStepsBarVariant,
} from '../shared/funnelStepsBarShared'

export const FUNNEL_STEPS_SERIES_KEY_PREFIX = 'funnel-step-series-'

/** Identifies which breakdown variant a hog-charts series maps back to, so click and
 *  tooltip handlers can recover the original `FunnelStepWithConversionMetrics`. */
export interface FunnelStepsBarSeriesMeta {
    breakdownIndex: number
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
    const seriesVariants: FunnelStepsBarVariant<FunnelStepsBarSeriesMeta>[] = []

    for (let breakdownIndex = 0; breakdownIndex < breakdownCount; breakdownIndex++) {
        const variants = steps.map((step) => variantAtStep(step, breakdownIndex, isBreakdown))
        const representative = variants[0]
        seriesVariants.push({
            key: `${FUNNEL_STEPS_SERIES_KEY_PREFIX}${breakdownIndex}`,
            label: representative ? options.getLabel(representative) : '',
            data: variants.map((variant) => variant.conversionRates.fromBasisStep * RATE_TO_PERCENT),
            color: representative ? options.getColor(representative) : undefined,
            meta: { breakdownIndex },
        })
    }

    return buildFunnelStepsBars(steps, seriesVariants)
}

/** Derives the chart config from the base config plus the two things that vary per render:
 *  whether the legend is needed (breakdown + compare) and whether the new pinnable tooltip is
 *  enabled. A breakdown always puts one series per breakdown value at each step, so a pinnable
 *  tooltip here always covers multiple series — `resolveClickToNearestSeries` resolves the
 *  click to the nearest one and opens its persons modal directly instead of pinning first. */
export function withFunnelStepsBarInteraction(
    baseConfig: BarChartConfig,
    options: { isBreakdownCompare?: boolean; quillTooltipEnabled: boolean }
): BarChartConfig {
    const base = options.isBreakdownCompare ? { ...baseConfig, legend: { show: true, interactive: false } } : baseConfig
    if (options.quillTooltipEnabled) {
        return {
            ...base,
            tooltip: { ...INSIGHT_TOOLTIP_CONFIG, resolveClickToNearestSeries: true },
        }
    }
    return base
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
