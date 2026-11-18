import { useEffect, useState } from 'react'

import {
    MINIMUM_DETECTABLE_EFFECT_MAX,
    MINIMUM_DETECTABLE_EFFECT_MIN,
    ManualCalculatorMetricType,
} from 'scenes/experiments/RunningTimeCalculator/calculations'

export const METRIC_TYPE_OPTIONS: { value: ManualCalculatorMetricType; label: string }[] = [
    { value: 'funnel', label: 'Funnel' },
    { value: 'mean_count', label: 'Count' },
    { value: 'mean_sum_or_avg', label: 'Sum/Avg' },
]

export const MANUAL_MODE_HELP = 'Enter your own values to calculate sample size and running time.'
export const AUTOMATIC_MODE_DISABLED_REASON = 'Available after launching experiment'
export const EXPOSURES_PER_DAY_HELP = 'Total users entering the experiment per day (across all variants).'
export const NOT_ENOUGH_DATA_NOTE =
    'Not enough data to estimate the running time yet. It needs exposures, and some activity on the primary metric, in each variant.'
export const MINIMUM_DETECTABLE_EFFECT_HELP =
    'The minimum detectable effect is the smallest change you want to detect, relative to the control. Smaller changes are harder to tell apart from random noise, so they need more exposures. It affects only the running time, not how the metrics are calculated.'
export const OUT_OF_REACH_TOOLTIP = 'More than 4 weeks from today. Most experiments end within 4 weeks.'

export function getBaselineLabel(metricType: ManualCalculatorMetricType): string {
    switch (metricType) {
        case 'funnel':
            return 'Baseline conversion rate'
        case 'mean_count':
            return 'Avg events per user'
        case 'mean_sum_or_avg':
            return 'Avg property value per user'
    }
}

export function getBaselineHelp(metricType: ManualCalculatorMetricType): string {
    switch (metricType) {
        case 'funnel':
            return 'Expected conversion rate for the control group (0-100%)'
        case 'mean_count':
            return 'Average number of events per user in the control group'
        case 'mean_sum_or_avg':
            return 'Average property value per user in the control group'
    }
}

/**
 * Switching to funnel reinterprets baselineValue as a conversion rate, so carry the same 100% clamp the baseline
 * input applies. Otherwise a large mean value survives the switch as an out-of-range rate.
 */
export function metricTypeChange(
    metricType: ManualCalculatorMetricType,
    baselineValue: number
): { metricType: ManualCalculatorMetricType; baselineValue?: number } {
    return { metricType, ...(metricType === 'funnel' && baselineValue > 100 ? { baselineValue: 100 } : {}) }
}

/**
 * A funnel conversion rate above 100% is impossible and makes the sample-size math produce a negative estimate.
 * Clamp it for real, since the input's `max` only guides the stepper.
 */
export function clampBaseline(metricType: ManualCalculatorMetricType, value: number): number {
    return metricType === 'funnel' && value > 100 ? 100 : value
}

export function formatRunningTime(days: number | null | undefined): string {
    return days ? `~${days} day${days !== 1 ? 's' : ''}` : '—'
}

const isInRange = (value: number | undefined): value is number =>
    value !== undefined && value >= MINIMUM_DETECTABLE_EFFECT_MIN && value <= MINIMUM_DETECTABLE_EFFECT_MAX

export const MINIMUM_DETECTABLE_EFFECT_RANGE_ERROR = `Enter a value from ${MINIMUM_DETECTABLE_EFFECT_MIN} to ${MINIMUM_DETECTABLE_EFFECT_MAX}.`

/**
 * The input keeps what the user types, so that an empty field or a partial number stays editable. Only a value in
 * range reaches the estimate.
 */
export function useMinimumDetectableEffectDraft(
    value: number,
    onChange: (value: number) => void
): {
    draft: number | undefined
    setDraftValue: (next: number | undefined) => void
    commitDraft: () => void
    outOfRange: boolean
} {
    const [draft, setDraft] = useState<number | undefined>(value)
    useEffect(() => setDraft(value), [value])
    const isDraftEmpty = draft === undefined || Number.isNaN(draft)

    return {
        draft,
        setDraftValue: (next) => {
            setDraft(next)
            if (isInRange(next)) {
                onChange(next)
            }
        },
        commitDraft: () => {
            if (draft === undefined || Number.isNaN(draft)) {
                setDraft(value)
            } else if (!isInRange(draft)) {
                const clamped = Math.min(MINIMUM_DETECTABLE_EFFECT_MAX, Math.max(MINIMUM_DETECTABLE_EFFECT_MIN, draft))
                setDraft(clamped)
                onChange(clamped)
            }
        },
        outOfRange: !isDraftEmpty && !isInRange(draft),
    }
}

/** The line under the detectable effect table: which metric it is based on and what the projection assumes. */
export function detectableEffectFootnote({
    estimateMetric,
    dailyExposureRate,
    isOutOfReach,
    canIncludeMoreUsers,
}: {
    estimateMetric: { name?: string | null; isFirstOfSeveral?: boolean; hasOtherMetrics?: boolean } | null | undefined
    dailyExposureRate: number
    isOutOfReach: boolean
    canIncludeMoreUsers: boolean
}): { metricName: string; rest: string } {
    return {
        metricName: estimateMetric?.name ?? 'the primary metric',
        rest: `${estimateMetric ? `, the ${estimateMetric.isFirstOfSeveral ? 'first ' : ''}primary metric` : ''}.${
            estimateMetric?.hasOtherMetrics ? ' Other metrics can need more time.' : ''
        } Projections assume about ${Math.round(dailyExposureRate).toLocaleString()} exposures a day, the average since launch.${
            isOutOfReach && canIncludeMoreUsers ? ' To finish sooner, include more users in the experiment.' : ''
        }`,
    }
}
