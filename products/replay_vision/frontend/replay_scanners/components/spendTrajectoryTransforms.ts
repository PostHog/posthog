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

export interface SpendReferenceLabel {
    key: 'limit' | 'free'
    value: number
    text: string
    tone: SpendMarkerTone
    position: 'start' | 'end'
}

export interface SpendPeriodAxis {
    firstDay: dayjs.Dayjs
    periodEnd: dayjs.Dayjs
    endIndex: number
    todayIndex: number
    labels: string[]
}

export interface SpendCrossing {
    index: number
    value: number
    date: dayjs.Dayjs
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
    freeCredits: number | null
    spentTotal: number
    endValue: number
    crossing: SpendCrossing | null
    pausedAtLimit: boolean
    periodEnd: dayjs.Dayjs
}

// The ledger is bucketed by UTC day, so the axis is UTC too: a local axis would shift the curve by a day.
export function buildSpendPeriodAxis(periodStart: string, periodEnd: string, now: dayjs.Dayjs): SpendPeriodAxis {
    const firstDay = dayjs.utc(periodStart).startOf('day')
    const end = dayjs.utc(periodEnd)
    const endIndex = Math.max(end.startOf('day').diff(firstDay, 'day'), 1)
    return {
        firstDay,
        periodEnd: end,
        endIndex,
        todayIndex: clamp(now.utc().startOf('day').diff(firstDay, 'day'), 0, endIndex),
        labels: Array.from({ length: endIndex + 1 }, (_, i) => firstDay.add(i, 'day').format('YYYY-MM-DD')),
    }
}

function emptySeries(axis: SpendPeriodAxis): number[] {
    return Array.from({ length: axis.labels.length }, () => NaN)
}

// Today reads `credits_used`, the number the card header shows. The ledger only shapes the curve: it is
// fetched alongside the quota and can be a moment newer, so only the days that overshoot are pulled down.
export function buildSpentSeries(dailyCredits: SpendSeries, spentTotal: number, axis: SpendPeriodAxis): number[] {
    const spent = emptySeries(axis)
    if (dailyCredits.length > 0) {
        const creditsByIndex = Array.from({ length: axis.todayIndex + 1 }, () => 0)
        for (const entry of dailyCredits) {
            const index = clamp(dayjs.utc(entry.date).diff(axis.firstDay, 'day'), 0, axis.todayIndex)
            creditsByIndex[index] += entry.credits
        }
        let runningTotal = 0
        for (let i = 0; i <= axis.todayIndex; i++) {
            runningTotal += creditsByIndex[i]
            spent[i] = runningTotal
        }
        for (let i = axis.todayIndex; i >= 0 && spent[i] > spentTotal; i--) {
            spent[i] = spentTotal
        }
    }
    spent[axis.todayIndex] = spentTotal
    return spent
}

export function resolveSpendCrossing(
    capReachDate: dayjs.Dayjs | null,
    cap: number | null,
    spentTotal: number,
    axis: SpendPeriodAxis
): SpendCrossing | null {
    if (cap === null || capReachDate === null || spentTotal >= cap) {
        return null
    }
    // Floored to its UTC day, so the dot sits on the day its own label names.
    const date = capReachDate.utc()
    const index = date.startOf('day').diff(axis.firstDay, 'day')
    return index > axis.todayIndex && index <= axis.endIndex ? { index, value: cap, date } : null
}

export function buildProjectedSeries(
    spentTotal: number,
    endValue: number,
    crossing: SpendCrossing | null,
    axis: SpendPeriodAxis
): number[] {
    const projected = emptySeries(axis)
    const toIndex = crossing?.index ?? axis.endIndex
    const toValue = crossing?.value ?? endValue
    const span = toIndex - axis.todayIndex
    for (let i = axis.todayIndex; i <= toIndex; i++) {
        projected[i] = span === 0 ? toValue : spentTotal + ((toValue - spentTotal) * (i - axis.todayIndex)) / span
    }
    return projected
}

// The free allocation gets its own quieter line, unless it is the limit (the free plan) or too close to read.
export function resolveFreeCreditsLine(free: number, cap: number | null, axisMax: number): number | null {
    const minLineGap = axisMax * MIN_LINE_GAP_RATIO
    return free >= minLineGap && (cap === null || cap - free >= minLineGap) ? free : null
}

export function buildSpendMarkers(
    spentTotal: number,
    endValue: number,
    crossing: SpendCrossing | null,
    axis: SpendPeriodAxis
): SpendMarker[] {
    const today: SpendMarker = {
        key: 'today',
        seriesKey: SPENT_SERIES_KEY,
        label: axis.labels[axis.todayIndex],
        value: spentTotal,
        text: `Today · ${formatCreditNumber(spentTotal)}`,
        tone: 'default',
    }
    const projectionEnd: SpendMarker = crossing
        ? {
              key: 'crossing',
              seriesKey: PROJECTED_SERIES_KEY,
              label: axis.labels[crossing.index],
              value: crossing.value,
              text: `Limit · ${crossing.date.format('MMM D')}`,
              tone: 'danger',
          }
        : {
              key: 'end',
              seriesKey: PROJECTED_SERIES_KEY,
              label: axis.labels[axis.endIndex],
              value: endValue,
              text: `${axis.periodEnd.format('MMM D')} · ~${formatCreditNumber(endValue)}`,
              tone: 'muted',
          }
    return [today, projectionEnd]
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
    const axis = buildSpendPeriodAxis(quota.period_start, quota.period_end, now)
    const spentTotal = quota.credits_used
    const cap = quota.credit_limit !== null && quota.credit_limit > 0 ? quota.credit_limit : null
    // Cumulative spend cannot go down, so the projection never dips below today.
    const demand = Math.max(projectedTotal, spentTotal)
    const endValue = cap !== null ? Math.min(demand, cap) : demand
    const pausedAtLimit = cap !== null && spentTotal >= cap
    const crossing = resolveSpendCrossing(capReachDate, cap, spentTotal, axis)
    const free = quota.free_monthly_credits
    const freeCredits = resolveFreeCreditsLine(free, cap, Math.max(cap ?? 0, endValue, spentTotal, free, 1))

    const series: Series[] = [
        {
            key: SPENT_SERIES_KEY,
            label: 'Spent',
            data: buildSpentSeries(dailyCredits, spentTotal, axis),
            fill: { opacity: 0.08 },
        },
        {
            key: PROJECTED_SERIES_KEY,
            label: 'Projected',
            data: buildProjectedSeries(spentTotal, endValue, crossing, axis),
            color: crossing || pausedAtLimit ? dangerColor : statusColor,
            stroke: { pattern: [4, 4] },
        },
    ]

    return {
        labels: axis.labels,
        series,
        markers: buildSpendMarkers(spentTotal, endValue, crossing, axis),
        cap,
        freeCredits,
        spentTotal,
        endValue,
        crossing,
        pausedAtLimit,
        periodEnd: axis.periodEnd,
    }
}
