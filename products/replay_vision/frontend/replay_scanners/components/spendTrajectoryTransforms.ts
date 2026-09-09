import type { Series } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { clamp } from 'lib/utils/numbers'

import type { VisionQuotaApi } from '../../generated/api.schemas'
import { formatCreditNumber } from '../../utils/credits'
import type { SpendSeries } from '../visionUsageLogic'

export const SPENT_SERIES_KEY = 'spent'
export const PROJECTED_SERIES_KEY = 'projected'

// Lines closer than this share of the axis, to each other or to zero, read as one.
const MIN_LINE_GAP_RATIO = 0.08

export type SpendMarkerTone = 'default' | 'muted' | 'danger'

export interface SpendMarker {
    key: 'today' | 'end' | 'crossing'
    seriesKey: string
    label: string
    value: number
    text: string
    tone: SpendMarkerTone
}

export interface SpendTrajectoryInput {
    quota: VisionQuotaApi
    /** Settled credits per UTC day of the period, oldest first. */
    dailyCredits: SpendSeries
    /** Credits the period is projected to end on, already held at the limit where one applies. */
    projectedTotal: number
    /** When demand crosses the limit inside the period, the date the verdict computed for it. */
    capReachDate: dayjs.Dayjs | null
    statusColor: string
    dangerColor: string
    now?: dayjs.Dayjs
}

export interface SpendTrajectory {
    labels: string[]
    series: Series[]
    markers: SpendMarker[]
    cap: number | null
    /** Null when there is no free line to draw: no allocation, it is the limit, or too close to read. */
    freeCredits: number | null
    spentTotal: number
    endValue: number
    crossingDate: dayjs.Dayjs | null
    pausedAtLimit: boolean
    periodEnd: dayjs.Dayjs
}

function lerpInto(data: number[], fromIndex: number, toIndex: number, fromValue: number, toValue: number): void {
    const span = toIndex - fromIndex
    for (let i = fromIndex; i <= toIndex; i++) {
        data[i] = span === 0 ? toValue : fromValue + ((toValue - fromValue) * (i - fromIndex)) / span
    }
}

/**
 * Cumulative spend across the period against the limit: a solid line to today and a dashed projection
 * to period end. Spend pauses at the limit, so the projection never exceeds it: when demand crosses,
 * the line stops at the crossing and the crossing carries the date.
 */
export function buildSpendTrajectory({
    quota,
    dailyCredits,
    projectedTotal,
    capReachDate,
    statusColor,
    dangerColor,
    now = dayjs.utc(),
}: SpendTrajectoryInput): SpendTrajectory {
    // The ledger is bucketed by UTC day, so the axis is UTC too; a local axis would shift the curve by a day.
    const firstDay = dayjs.utc(quota.period_start).startOf('day')
    const periodEnd = dayjs.utc(quota.period_end)
    const endIndex = Math.max(periodEnd.startOf('day').diff(firstDay, 'day'), 1)
    const labels = Array.from({ length: endIndex + 1 }, (_, i) => firstDay.add(i, 'day').format('YYYY-MM-DD'))
    const todayIndex = clamp(now.utc().startOf('day').diff(firstDay, 'day'), 0, endIndex)

    const spent = Array.from({ length: labels.length }, () => NaN)
    const spentTotal = quota.credits_used
    if (dailyCredits.length > 0) {
        const creditsByIndex = Array.from({ length: todayIndex + 1 }, () => 0)
        for (const entry of dailyCredits) {
            const index = clamp(dayjs.utc(entry.date).diff(firstDay, 'day'), 0, todayIndex)
            creditsByIndex[index] += entry.credits
        }
        let runningTotal = 0
        for (let i = 0; i <= todayIndex; i++) {
            runningTotal += creditsByIndex[i]
            spent[i] = runningTotal
        }
        // The card header reads `credits_used`, so today's point is that number and the ledger only gives
        // the curve its shape. The series is fetched alongside the quota and can be a moment newer, so only
        // the tail is pulled down to it: clamping every point would draw days of zero spend that never happened.
        for (let i = todayIndex; i >= 0 && spent[i] > spentTotal; i--) {
            spent[i] = spentTotal
        }
    }
    spent[todayIndex] = spentTotal

    // A zero or missing limit draws no cap; spend stops at a real one, so the drawn end never exceeds it
    // and demand only decides the slope. Cumulative spend cannot go down, so it never dips below today either.
    const cap = quota.credit_limit !== null && quota.credit_limit > 0 ? quota.credit_limit : null
    const demand = Math.max(projectedTotal, spentTotal)
    const endValue = cap !== null ? Math.min(demand, cap) : demand
    const pausedAtLimit = cap !== null && spentTotal >= cap

    // The crossing sits on the verdict's date, so the dot, its label and the tile all name the same day.
    const crossingIndex =
        cap !== null && capReachDate && spentTotal < cap
            ? Math.ceil(capReachDate.utc().diff(firstDay, 'day', true))
            : null
    const crossing = crossingIndex !== null && crossingIndex > todayIndex && crossingIndex <= endIndex
    const projected = Array.from({ length: labels.length }, () => NaN)
    if (crossing) {
        lerpInto(projected, todayIndex, crossingIndex, spentTotal, cap ?? 0)
    } else {
        lerpInto(projected, todayIndex, endIndex, spentTotal, endValue)
    }

    // The free allocation gets its own quieter line, unless it IS the limit (the free plan).
    const free = quota.free_monthly_credits
    const axisMax = Math.max(cap ?? 0, endValue, spentTotal, free, 1)
    const minLineGap = axisMax * MIN_LINE_GAP_RATIO
    const freeCredits = free >= minLineGap && (cap === null || cap - free >= minLineGap) ? free : null

    const series: Series[] = [
        { key: SPENT_SERIES_KEY, label: 'Spent', data: spent, fill: { opacity: 0.08 } },
        {
            key: PROJECTED_SERIES_KEY,
            label: 'Projected',
            data: projected,
            color: crossing || pausedAtLimit ? dangerColor : statusColor,
            stroke: { pattern: [4, 4] },
        },
    ]

    const markers: SpendMarker[] = [
        {
            key: 'today',
            seriesKey: SPENT_SERIES_KEY,
            label: labels[todayIndex],
            value: spentTotal,
            text: `Today · ${formatCreditNumber(spentTotal)}`,
            tone: 'default',
        },
        crossing
            ? {
                  key: 'crossing',
                  seriesKey: PROJECTED_SERIES_KEY,
                  label: labels[crossingIndex],
                  value: cap ?? 0,
                  text: `Limit · ${capReachDate?.format('MMM D')}`,
                  tone: 'danger',
              }
            : {
                  key: 'end',
                  seriesKey: PROJECTED_SERIES_KEY,
                  label: labels[endIndex],
                  value: endValue,
                  text: `${periodEnd.format('MMM D')} · ~${formatCreditNumber(endValue)}`,
                  tone: 'muted',
              },
    ]

    return {
        labels,
        series,
        markers,
        cap,
        freeCredits,
        spentTotal,
        endValue,
        crossingDate: crossing ? capReachDate : null,
        pausedAtLimit,
        periodEnd,
    }
}
