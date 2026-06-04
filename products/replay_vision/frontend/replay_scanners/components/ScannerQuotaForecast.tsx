import { useValues } from 'kea'

import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { replayScannerLogic } from '../replayScannerLogic'

interface Props {
    scannerId: string
    tabId: string
}

const WARN_THRESHOLD = 0.8
const MIN_DAYS_FOR_PROJECTED_DATE = 3

type QuotaStatus = 'safe' | 'warning' | 'danger'

const STATUS_STYLES: Record<QuotaStatus, { bar: string; text: string }> = {
    safe: { bar: 'bg-primary', text: 'text-muted' },
    warning: { bar: 'bg-warning', text: 'text-warning' },
    danger: { bar: 'bg-danger', text: 'text-danger' },
}

export function ScannerQuotaForecast({ scannerId, tabId }: Props): JSX.Element | null {
    const { scanner, scannerEstimate, scannerEstimateLoading } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    const { quota } = useValues(visionQuotaLogic)

    if (!scanner) {
        return null
    }

    const samplingRatio = Math.max(0, Math.min(scanner.sampling_rate, 1))
    const projected = scannerEstimate?.estimated_observations_per_month ?? null
    const hasCap = !!quota && quota.monthly_quota > 0
    const used = quota?.usage_this_month ?? 0
    const cap = quota?.monthly_quota ?? 0

    const now = dayjs()
    const periodStart = quota?.period_start ? dayjs(quota.period_start) : null
    const periodEnd = quota?.period_end ? dayjs(quota.period_end) : null
    const periodLengthDays = periodStart && periodEnd ? Math.max(periodEnd.diff(periodStart, 'day', true), 1) : 30
    const daysElapsed = periodStart ? Math.max(now.diff(periodStart, 'day', true), 0) : 0
    const daysRemaining = periodEnd ? Math.max(periodEnd.diff(now, 'day', true), 0) : 0
    const resetsOn = periodEnd ? periodEnd.format('MMM D') : null

    // Daily burn = current period's running average. Scanner adds its projection spread across the period.
    const historicalDailyBurn = daysElapsed > 0 ? used / daysElapsed : 0
    const scannerDailyRate = projected !== null ? projected / periodLengthDays : 0
    const combinedDailyRate = historicalDailyBurn + scannerDailyRate
    const projectionConfident = daysElapsed >= MIN_DAYS_FOR_PROJECTED_DATE

    // "If saved now, what % of cap will the org sit at by period end?"
    const projectedPeriodEndUsage = hasCap && projected !== null ? used + combinedDailyRate * daysRemaining : 0
    const projectedPeriodEndRatio = hasCap ? projectedPeriodEndUsage / cap : 0

    const capReachDate =
        hasCap && combinedDailyRate > 0 && used < cap ? now.add((cap - used) / combinedDailyRate, 'day') : null
    const capReachInPeriod = !!(capReachDate && periodEnd && capReachDate.isBefore(periodEnd))

    const status: QuotaStatus =
        !hasCap || projected === null
            ? 'safe'
            : capReachInPeriod
              ? 'danger'
              : projectedPeriodEndRatio >= WARN_THRESHOLD
                ? 'warning'
                : 'safe'
    const styles = STATUS_STYLES[status]
    const percentLabel = hasCap ? Math.min(Math.round(projectedPeriodEndRatio * 100), 999) : 0

    // Bar segments reflect the same "by period end" story: current usage + scanner's remaining-period contribution.
    const usedPct = hasCap ? Math.min((used / cap) * 100, 100) : 0
    const additionalUsagePct =
        hasCap && projected !== null ? Math.min((scannerDailyRate * daysRemaining * 100) / cap, 100 - usedPct) : 0
    const overflowPct = hasCap && projectedPeriodEndUsage > cap ? ((projectedPeriodEndUsage - cap) / cap) * 100 : 0

    const renderBreakdown = (): JSX.Element => (
        <div className="text-xs space-y-0.5">
            <div>
                Used this month: <strong>{used.toLocaleString()}</strong>
            </div>
            <div>
                Projected from this scanner: <strong>~{(projected ?? 0).toLocaleString()}/month</strong>
            </div>
            <div>
                Monthly cap: <strong>{cap.toLocaleString()}</strong>
            </div>
            {resetsOn && <div className="text-muted">Resets {resetsOn}</div>}
        </div>
    )

    const renderStatusLine = (): JSX.Element | string => {
        if (status === 'danger') {
            if (capReachDate && projectionConfident) {
                return (
                    <span className="text-danger">
                        Cap reached on <strong>{capReachDate.format('MMM D')}</strong> at this rate.
                    </span>
                )
            }
            return <span className="text-danger">Projected to exceed your monthly cap.</span>
        }
        if (status === 'warning') {
            return <span className="text-warning">Approaching cap by {resetsOn ?? 'period end'} at this rate.</span>
        }
        if (hasCap) {
            return <>Should last the month at this rate.</>
        }
        return (
            <>
                Based on <strong>{scannerEstimate?.matched_sessions_in_window.toLocaleString() ?? 0}</strong> matching
                recordings in the last {scannerEstimate?.window_days ?? 0} days.
            </>
        )
    }

    return (
        <div className="border rounded p-3 bg-bg-light space-y-2">
            <div className="flex items-baseline justify-between gap-3">
                <div className="text-xs font-medium uppercase tracking-wide text-muted">Estimated impact</div>
                {hasCap && projected !== null && (
                    <Tooltip title={renderBreakdown()}>
                        <span className={`text-xs tabular-nums ${styles.text}`}>
                            {percentLabel}%{' '}
                            <span className="text-muted font-normal">by {resetsOn ?? 'period end'}</span>
                        </span>
                    </Tooltip>
                )}
            </div>

            <div className="flex items-baseline justify-between gap-3">
                {projected !== null ? (
                    <div className="text-base font-semibold tabular-nums">
                        {projected.toLocaleString()}{' '}
                        <span className="text-sm font-normal text-muted">observations/month</span>
                    </div>
                ) : (
                    <div className="text-sm text-muted">—</div>
                )}
                {hasCap && (
                    <span className="text-xs text-muted tabular-nums">
                        {used.toLocaleString()} / {cap.toLocaleString()}
                    </span>
                )}
            </div>

            {hasCap && projected !== null && (
                <Tooltip title={renderBreakdown()}>
                    <div
                        className="flex h-1.5 rounded overflow-hidden bg-border-light"
                        role="meter"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={percentLabel}
                        aria-label={`Projected ${percentLabel}% of monthly observation quota by ${
                            resetsOn ?? 'period end'
                        }`}
                    >
                        <div className="bg-muted" style={{ width: `${usedPct}%` }} />
                        <div className={styles.bar} style={{ width: `${additionalUsagePct}%` }} />
                        {overflowPct > 0 && (
                            <div className="bg-danger opacity-60" style={{ width: `${Math.min(overflowPct, 100)}%` }} />
                        )}
                    </div>
                </Tooltip>
            )}

            {samplingRatio === 0 ? (
                <div className="text-xs text-danger">
                    Sampling is 0%. This scanner will not produce any observations.
                </div>
            ) : scannerEstimateLoading && !scannerEstimate ? (
                <div className="text-xs text-muted flex items-center gap-2">
                    <Spinner /> Estimating from your filters…
                </div>
            ) : scannerEstimate ? (
                <div className="text-xs text-muted">{renderStatusLine()}</div>
            ) : (
                <div className="text-xs text-muted">Estimate unavailable. Try adjusting your filters.</div>
            )}
        </div>
    )
}
