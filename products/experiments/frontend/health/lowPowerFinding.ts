import type { MetricWithResult } from 'scenes/experiments/utils'

import { isExperimentFunnelMetric } from '~/queries/schema/schema-general'

import { EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS } from '../constants'
import type { HealthPanelFinding } from './healthPanelFindings'

// A funnel needs about 16 · (1 - p) / MDE² conversions per variant to detect a relative change of MDE with
// 80% power. For a 20% change and a low conversion rate, that is about 400.
export const LOW_POWER_MIN_CONVERSIONS_PER_VARIANT = 400
// Below this share of the running time calculator's recommended sample size, the experiment is far from
// the power it was planned for.
export const LOW_POWER_SAMPLE_SIZE_SHARE = 0.5

// pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
export const FEW_CONVERSIONS = 'few_conversions'
export const BELOW_RECOMMENDED_SAMPLE_SIZE = 'below_recommended_sample_size'

const LOW_POWER_TITLE = 'Too little data to trust the results'
const LOW_POWER_NEXT_STEP =
    'Differences between variants can be noise, also when they look large. Let the experiment run longer, test a ' +
    'bigger change, or measure an earlier step of the funnel, which more users complete.'

/** The fewest conversions of a variant across the primary funnel metrics with results, or null when none has results. */
export function fewestConversionsPerVariant(primaryMetrics: MetricWithResult[]): number | null {
    const conversions = primaryMetrics.flatMap(({ metric, result }) =>
        isExperimentFunnelMetric(metric) && result?.baseline
            ? [result.baseline.sum, ...(result.variant_results ?? []).map((variant) => variant.sum)]
            : []
    )
    return conversions.length ? Math.min(...conversions) : null
}

/**
 * Warns that the results rest on too little data to tell a real difference from noise. Only shown once the
 * page unlocks the results, because before that the page shows no results to misread.
 */
export function lowPowerFinding({
    primaryMetrics,
    totalExposures,
    recommendedSampleSize,
    isExperimentDraft,
}: {
    primaryMetrics: MetricWithResult[]
    totalExposures: number
    recommendedSampleSize: number | null | undefined
    isExperimentDraft: boolean
}): HealthPanelFinding | null {
    if (isExperimentDraft || totalExposures < EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS) {
        return null
    }
    const reachedRecommendedSampleSize = !!recommendedSampleSize && totalExposures >= recommendedSampleSize

    const fewestConversions = fewestConversionsPerVariant(primaryMetrics)
    // The running time calculator's plan is a better reference than the fixed threshold, so a sample that
    // reached it gets no conversions warning.
    if (
        !reachedRecommendedSampleSize &&
        fewestConversions !== null &&
        fewestConversions < LOW_POWER_MIN_CONVERSIONS_PER_VARIANT
    ) {
        return {
            code: 'low_power',
            subcode: FEW_CONVERSIONS,
            severity: 'info',
            title: LOW_POWER_TITLE,
            detail:
                `A variant of a primary funnel metric has only ${fewestConversions.toLocaleString()} conversions. ` +
                `With fewer than ${LOW_POWER_MIN_CONVERSIONS_PER_VARIANT.toLocaleString()} conversions per variant, ` +
                `only very large differences are reliable. ${LOW_POWER_NEXT_STEP}`,
            evidence: { fewest_conversions_per_variant: fewestConversions },
            actions: [],
        }
    }

    if (recommendedSampleSize && totalExposures < recommendedSampleSize * LOW_POWER_SAMPLE_SIZE_SHARE) {
        return {
            code: 'low_power',
            subcode: BELOW_RECOMMENDED_SAMPLE_SIZE,
            severity: 'info',
            title: LOW_POWER_TITLE,
            detail:
                `The experiment has ${totalExposures.toLocaleString()} exposures. The running time calculator ` +
                `recommends ${recommendedSampleSize.toLocaleString()} to detect the minimum effect you set. ` +
                LOW_POWER_NEXT_STEP,
            evidence: { total_exposures: totalExposures, recommended_sample_size: recommendedSampleSize },
            actions: [],
        }
    }

    return null
}
