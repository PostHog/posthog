import { useValues } from 'kea'

import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { type QuotaStatus, projectQuota } from '../../utils/quotaProjection'
import { replayScannerLogic } from '../replayScannerLogic'

interface Props {
    scannerId: string
    tabId: string
}

const STATUS_STYLES: Record<QuotaStatus, { bar: string; text: string }> = {
    safe: { bar: 'bg-primary', text: 'text-muted' },
    warning: { bar: 'bg-warning', text: 'text-warning' },
    danger: { bar: 'bg-danger', text: 'text-danger' },
}

export function ScannerQuotaForecast({ scannerId, tabId }: Props): JSX.Element | null {
    const { scanner, scannerEstimate, scannerEstimateLoading, isNew } = useValues(
        replayScannerLogic({ id: scannerId, tabId })
    )
    const { quota } = useValues(visionQuotaLogic)

    if (!scanner) {
        return null
    }

    const samplingRatio = Math.max(0, Math.min(scanner.sampling_rate, 1))
    const projected = scannerEstimate?.estimated_observations_per_month ?? null
    const hasCap = !!quota && quota.monthly_quota > 0
    const used = quota?.usage_this_month ?? 0
    const cap = quota?.monthly_quota ?? 0

    // On edit, this scanner's existing contribution is already inside `usage_this_month`, so adding
    // its projection on top of historical burn would double-count. Skip the addition; the headline
    // number still reads the new projection so the user can compare it to current burn.
    const projection = projectQuota(quota, isNew ? projected : null)
    const {
        status,
        capReachDate,
        projectionConfident,
        projectedPeriodEndRatio,
        resetsOn,
        daysRemaining,
        combinedDailyRate,
    } = projection

    const effectiveStatus: QuotaStatus = projected === null ? 'safe' : status
    const styles = STATUS_STYLES[effectiveStatus]
    const percentLabel = hasCap ? Math.round(projectedPeriodEndRatio * 100) : 0

    const usedPct = hasCap ? Math.min((used / cap) * 100, 100) : 0
    const additionalUsagePct =
        hasCap && projected !== null ? Math.min((combinedDailyRate * daysRemaining * 100) / cap, 100 - usedPct) : 0
    const projectedPeriodEndUsage = used + (projected !== null ? combinedDailyRate * daysRemaining : 0)
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
        if (effectiveStatus === 'danger') {
            if (capReachDate && projectionConfident) {
                return (
                    <span className="text-danger">
                        Cap reached on <strong>{capReachDate.format('MMM D')}</strong> at this rate.
                    </span>
                )
            }
            return <span className="text-danger">Projected to exceed your monthly cap.</span>
        }
        if (effectiveStatus === 'warning') {
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
                    <div className="text-base font-semibold tabular-nums flex items-baseline gap-2">
                        <span>
                            {projected.toLocaleString()}{' '}
                            <span className="text-sm font-normal text-muted">observations/month</span>
                        </span>
                        {scannerEstimateLoading && (
                            <Tooltip title="Recomputing with the latest filters and sampling rate.">
                                <Spinner className="text-muted text-sm" />
                            </Tooltip>
                        )}
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
