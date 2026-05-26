import type { Series } from 'lib/hog-charts'

import type { FunnelStepWithConversionMetrics } from '~/types'

export const FUNNEL_STEPS_SERIES_KEY_PREFIX = 'funnel-step-series-'

/** `conversionRates.fromBasisStep` is a 0–1 ratio; hog-charts bars are valued in percent. */
const RATE_TO_PERCENT = 100

/** Identifies which breakdown variant a hog-charts series maps back to, so click and
 *  tooltip handlers can recover the original `FunnelStepWithConversionMetrics`. */
export interface FunnelStepsBarSeriesMeta {
    breakdownIndex: number
}

interface BuildOptions {
    getColor: (series: FunnelStepWithConversionMetrics) => string
    getLabel: (series: FunnelStepWithConversionMetrics) => string
}

export interface FunnelStepsBarData {
    /** One series per breakdown variant; `data[stepIndex]` is a percent (0–100). */
    series: Series<FunnelStepsBarSeriesMeta>[]
    labels: string[]
}

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
 *  variant, one bar per step, valued by conversion rate from the basis step. */
export function buildFunnelStepsBarData(
    steps: FunnelStepWithConversionMetrics[],
    options: BuildOptions
): FunnelStepsBarData {
    if (steps.length === 0) {
        return { series: [], labels: [] }
    }

    const isBreakdown = steps[0].nested_breakdown != null
    const breakdownCount = isBreakdown ? steps[0].nested_breakdown!.length : 1
    const series: Series<FunnelStepsBarSeriesMeta>[] = []

    for (let breakdownIndex = 0; breakdownIndex < breakdownCount; breakdownIndex++) {
        const variants = steps.map((step) => variantAtStep(step, breakdownIndex, isBreakdown))
        const representative = variants[0]
        series.push({
            key: `${FUNNEL_STEPS_SERIES_KEY_PREFIX}${breakdownIndex}`,
            label: representative ? options.getLabel(representative) : '',
            data: variants.map((variant) => variant.conversionRates.fromBasisStep * RATE_TO_PERCENT),
            color: representative ? options.getColor(representative) : undefined,
            meta: { breakdownIndex },
        })
    }

    return { series, labels: steps.map((_, stepIndex) => `${stepIndex + 1}`) }
}
