import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'

const WARN_THRESHOLD = 0.8
const MIN_DAYS_FOR_PROJECTED_DATE = 3

export function VisionQuotaMeter(): JSX.Element | null {
    const { quota, quotaLoading } = useValues(visionQuotaLogic)

    if (!quota) {
        if (quotaLoading) {
            return (
                <div className="border rounded p-3 bg-bg-light space-y-2">
                    <div className="flex items-center justify-between">
                        <LemonSkeleton className="h-4 w-48" />
                        <LemonSkeleton className="h-4 w-20" />
                    </div>
                    <LemonSkeleton className="h-2 w-full" />
                    <LemonSkeleton className="h-3 w-24" />
                </div>
            )
        }
        return null
    }

    const used = quota.usage_this_month
    const cap = quota.monthly_quota
    const hasCap = cap > 0
    const ratio = hasCap ? Math.min(used / cap, 1) : 0
    const percent = Math.round(ratio * 100)

    const now = dayjs()
    const periodStart = quota.period_start ? dayjs(quota.period_start) : null
    const periodEnd = quota.period_end ? dayjs(quota.period_end) : null
    const daysElapsed = periodStart ? Math.max(now.diff(periodStart, 'day', true), 0) : 0
    const daysRemaining = periodEnd ? Math.max(periodEnd.diff(now, 'day', true), 0) : 0
    const resetsOn = periodEnd ? periodEnd.format('MMM D') : null
    const projectionConfident = daysElapsed >= MIN_DAYS_FOR_PROJECTED_DATE

    const historicalDailyBurn = daysElapsed > 0 ? used / daysElapsed : 0
    const projectedPeriodEndUsage = hasCap ? used + historicalDailyBurn * daysRemaining : 0
    const projectedPeriodEndRatio = hasCap ? projectedPeriodEndUsage / cap : 0
    const capReachDate =
        hasCap && historicalDailyBurn > 0 && used < cap ? now.add((cap - used) / historicalDailyBurn, 'day') : null
    const capReachInPeriod = !!(capReachDate && periodEnd && capReachDate.isBefore(periodEnd))

    const strokeColor =
        quota.exhausted || capReachInPeriod
            ? 'var(--danger)'
            : projectedPeriodEndRatio >= WARN_THRESHOLD
              ? 'var(--warning)'
              : 'var(--success)'

    const renderFooter = (): JSX.Element => {
        if (quota.exhausted) {
            return <span className="text-danger">Quota reached.</span>
        }
        if (capReachInPeriod && projectionConfident && capReachDate) {
            return (
                <span className="text-danger">
                    {quota.remaining.toLocaleString()} remaining. Cap reached on{' '}
                    <strong>{capReachDate.format('MMM D')}</strong> at this rate.
                </span>
            )
        }
        if (projectedPeriodEndRatio >= WARN_THRESHOLD && projectionConfident) {
            return (
                <span className="text-warning">
                    {quota.remaining.toLocaleString()} remaining. Approaching cap by {resetsOn ?? 'period end'} at this
                    rate.
                </span>
            )
        }
        return (
            <>
                {quota.remaining.toLocaleString()} remaining{resetsOn ? `. Resets ${resetsOn}.` : '.'}
            </>
        )
    }

    return (
        <div className="border rounded p-3 bg-bg-light space-y-2">
            <div className="flex items-center justify-between">
                <Tooltip title="Observations are paused once this quota is reached, until next month.">
                    <span className="text-sm font-medium">Vision observations this month</span>
                </Tooltip>
                <span className="text-sm tabular-nums">
                    {used.toLocaleString()} / {cap.toLocaleString()}
                </span>
            </div>
            <LemonProgress percent={percent} strokeColor={strokeColor} />
            <div className="text-xs text-muted">{renderFooter()}</div>
        </div>
    )
}
