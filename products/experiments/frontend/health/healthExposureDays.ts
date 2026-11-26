import { dayjs } from 'lib/dayjs'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { EXPERIMENT_VARIANT_MULTIPLE } from '../constants'

/** The persons or groups that each compared variant first exposed on each day of the exposure answer. */
export interface HealthDailyExposures {
    days: string[]
    variants: { variant: string; counts: number[] }[]
}

export function healthDailyExposures(
    exposures: ExperimentExposureQueryResponse | null | undefined
): HealthDailyExposures | null {
    const expected = exposures?.sample_ratio_mismatch?.expected
    // The variants that the sample ratio test compares, as in the split table.
    const compared = (exposures?.timeseries ?? []).filter(({ variant }) =>
        expected ? variant in expected : variant !== EXPERIMENT_VARIANT_MULTIPLE
    )
    if (compared.length < 2 || compared[0].days.length === 0) {
        return null
    }
    return {
        days: compared[0].days,
        variants: compared.map(({ variant, exposure_counts }) => ({
            variant,
            // The answer counts each day cumulatively.
            counts: exposure_counts.map((count, index) => count - (index > 0 ? exposure_counts[index - 1] : 0)),
        })),
    }
}

// On a day with fewer, one person moves a share by several points, so the lines would jump without meaning anything.
const MINIMUM_DAILY_COUNT_FOR_SHARES = 30

/** Each variant's share of the persons or groups first exposed on each day, in percent. NaN on a day with too few. */
export function healthDailyShares(daily: HealthDailyExposures): { variant: string; shares: number[] }[] {
    const dayTotals = daily.days.map((_, index) =>
        daily.variants.reduce((total, { counts }) => total + counts[index], 0)
    )
    return daily.variants.map(({ variant, counts }) => ({
        variant,
        shares: counts.map((count, index) =>
            dayTotals[index] >= MINIMUM_DAILY_COUNT_FOR_SHARES ? (count / dayTotals[index]) * 100 : NaN
        ),
    }))
}

/** The day of the exposure answer that a time falls on. The answer dates each exposure in the project's timezone. */
export function healthExposureDay(time: string, timezone: string): string {
    return dayjs(time).tz(timezone).format('YYYY-MM-DD')
}
