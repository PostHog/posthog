import type { PointClickData } from '@posthog/quill-charts'

import { hasBreakdown } from 'scenes/funnels/funnelUtils'

import type { FunnelStepWithConversionMetrics } from '~/types'

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
    // Only pure period-vs-period compare gets the capped track + "not present" band. In breakdown ×
    // compare a bar's headroom mixes "smaller breakdown value" with "smaller period", so the
    // period-specific framing doesn't apply — those keep a full-axis track.
    const isPureCompare =
        (steps[0].nested_breakdown?.some((variant) => variant.compare_label != null) ?? false) &&
        !(steps[0].nested_breakdown ?? []).some((variant) => hasBreakdown(variant.breakdown_value))
    const seriesVariants: FunnelStepsBarVariant<FunnelStepsBarSeriesMeta>[] = []

    for (let breakdownIndex = 0; breakdownIndex < breakdownCount; breakdownIndex++) {
        const variants = steps.map((step) => variantAtStep(step, breakdownIndex, isBreakdown))
        const representative = variants[0]
        // Cap the track at this period's own entry level (its step-0 fraction of the shared baseline)
        // so the headroom above reads as "not present", not drop-off. The larger period sits at 100%
        // and keeps a full-axis track (no cap).
        const capPercent = (representative?.conversionRates.fromBasisStep ?? 1) * RATE_TO_PERCENT
        seriesVariants.push({
            key: `${FUNNEL_STEPS_SERIES_KEY_PREFIX}${breakdownIndex}`,
            label: representative ? options.getLabel(representative) : '',
            data: variants.map((variant) => variant.conversionRates.fromBasisStep * RATE_TO_PERCENT),
            color: representative ? options.getColor(representative) : undefined,
            meta: { breakdownIndex },
            trackMax: isPureCompare && capPercent < RATE_TO_PERCENT ? capPercent : undefined,
        })
    }

    // The left-to-right (grouped) layout renders the previous period before the current one — the
    // reverse of the nested_breakdown order ([current, previous] per pair) that the top-to-bottom
    // layout keeps. Swap within each confirmed current→previous pair (one pair for pure compare, one
    // per breakdown value for breakdown × compare); `meta.breakdownIndex` is unchanged, so click and
    // tooltip routing still resolve the right period.
    const nestedBreakdown = steps[0].nested_breakdown
    for (let i = 0; i + 1 < seriesVariants.length; i += 2) {
        if (
            nestedBreakdown?.[i]?.compare_label === 'current' &&
            nestedBreakdown?.[i + 1]?.compare_label === 'previous'
        ) {
            const current = seriesVariants[i]
            seriesVariants[i] = seriesVariants[i + 1]
            seriesVariants[i + 1] = current
        }
    }

    return buildFunnelStepsBars(steps, seriesVariants)
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
    clickData: Pick<PointClickData<FunnelStepsBarSeriesMeta>, 'dataIndex' | 'series' | 'inTrackArea' | 'beyondTrackMax'>
): FunnelStepClickTarget | null {
    // The headroom above a capped track is the "not present" volume gap — no actors, so inert.
    if (clickData.beyondTrackMax) {
        return null
    }
    const step = steps[clickData.dataIndex]
    if (!step) {
        return null
    }
    const breakdownIndex = clickData.series.meta?.breakdownIndex ?? 0
    const variant = step.nested_breakdown?.[breakdownIndex] ?? step
    return { step, series: variant, converted: !clickData.inTrackArea }
}
