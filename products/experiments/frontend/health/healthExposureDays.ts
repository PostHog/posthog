import { dayjs } from 'lib/dayjs'
import { getVariantColor } from 'scenes/experiments/utils'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'
import type { MultivariateFlagVariant } from '~/types'

import { healthIsComparedVariant } from './healthCheckValues'

/** The persons or groups that each compared variant first exposed on each day of the exposure answer. */
export interface HealthDailyExposures {
    days: string[]
    variants: { variant: string; counts: number[] }[]
}

export function healthDailyExposures(
    exposures: ExperimentExposureQueryResponse | null | undefined
): HealthDailyExposures | null {
    const expected = exposures?.sample_ratio_mismatch?.expected
    const compared = (exposures?.timeseries ?? []).filter(({ variant }) => healthIsComparedVariant(variant, expected))
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
const MINIMUM_DAYS_WITH_SHARES = 2

/** Each variant's share of the persons or groups first exposed on each day, in percent. NaN on a day with too few. */
export function healthDailyShares(daily: HealthDailyExposures): { variant: string; shares: number[] }[] | null {
    const dayTotals = daily.days.map((_, index) =>
        daily.variants.reduce((total, { counts }) => total + counts[index], 0)
    )
    if (dayTotals.filter((total) => total >= MINIMUM_DAILY_COUNT_FOR_SHARES).length < MINIMUM_DAYS_WITH_SHARES) {
        return null
    }
    return daily.variants.map(({ variant, counts }) => ({
        variant,
        shares: counts.map((count, index) =>
            dayTotals[index] >= MINIMUM_DAILY_COUNT_FOR_SHARES ? (count / dayTotals[index]) * 100 : NaN
        ),
    }))
}

/** The answer dates each exposure in the project's timezone, so a change is placed in it too. */
export function healthChangeDays(changedAt: string[], timezone: string, days: string[]): string[] {
    const changeDays = new Set(changedAt.map((time) => dayjs(time).tz(timezone).format('YYYY-MM-DD')))
    return days.filter((day) => changeDays.has(day))
}

// None for a variant the flag lacks, because the canvas can't draw the CSS variable that getVariantColor falls back to.
export function healthVariantColor(variant: string, flagVariants: MultivariateFlagVariant[]): string | undefined {
    return flagVariants.some(({ key }) => key === variant) ? getVariantColor(variant, flagVariants) : undefined
}
