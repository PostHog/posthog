import { useValues } from 'kea'

import { LemonCard, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { QUOTA_STATUS_STYLES, type QuotaStatus, projectQuota, splitProjectedPct } from '../../utils/quotaProjection'
import { replayScannerLogic } from '../replayScannerLogic'
import { QuotaMeterBar, QuotaMeterLegendItem } from './QuotaMeterBar'
import { QuotaStatusLine } from './QuotaStatusLine'

interface Props {
    scannerId: string
}

export function ScannerQuotaForecast({ scannerId }: Props): JSX.Element | null {
    const { scanner, scannerEstimate, scannerEstimateLoading, scannerEstimateError } = useValues(
        replayScannerLogic({ id: scannerId })
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

    // `other_enabled_scanners_monthly` comes from the same estimate response as `projected`, so the two are a
    // consistent snapshot. Subtracting this scanner's stored estimate from the live fleet sum instead would race the
    // estimate-refresh cadence and double-count the scanner right after creating it.
    const fleetMonthly = quota?.projected_monthly_observations ?? 0
    const othersMonthly = scannerEstimate?.other_enabled_scanners_monthly ?? 0
    // projectQuota wants a delta off the stored fleet total, so compute the new fleet total (others + this) and pass the difference.
    const newFleetMonthly = projected !== null ? othersMonthly + projected : fleetMonthly
    const projection = projectQuota(quota, newFleetMonthly - fleetMonthly)
    const { status, percentLabel, resetsOn, usedPct, projectedPct } = projection

    const effectiveStatus: QuotaStatus = projected === null ? 'safe' : status
    const styles = QUOTA_STATUS_STYLES[effectiveStatus]

    const { thisScannerPct, othersPct } = splitProjectedPct(projectedPct, projected ?? 0, othersMonthly)

    const breakdown = (
        <div className="text-xs space-y-0.5">
            <div>
                Used this month: <strong>{used.toLocaleString()}</strong>
            </div>
            <div>
                Projected from this scanner: <strong>~{(projected ?? 0).toLocaleString()}/month</strong>
            </div>
            <div>
                Projected from other scanners: <strong>~{othersMonthly.toLocaleString()}/month</strong>
            </div>
            <div>
                Monthly quota: <strong>{cap.toLocaleString()}</strong>
            </div>
            {resetsOn && <div className="text-muted">Resets {resetsOn}</div>}
        </div>
    )

    return (
        <LemonCard hoverEffect={false} className="p-3 space-y-2">
            <div className="flex items-baseline justify-between gap-3">
                <LemonLabel>Estimated impact</LemonLabel>
                {hasCap && projected !== null && (
                    <Tooltip title={breakdown}>
                        <span className={`text-xs tabular-nums ${styles.text}`}>
                            {percentLabel}%{' '}
                            <span className="text-muted font-normal">by {resetsOn ?? 'period end'}</span>
                        </span>
                    </Tooltip>
                )}
            </div>

            <div className="flex items-baseline justify-between gap-3">
                {projected !== null ? (
                    <div className="text-base font-semibold tabular-nums flex items-center gap-2">
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
                    <span className="text-xs tabular-nums">
                        <QuotaStatusLine projection={projection} />
                    </span>
                )}
            </div>

            {hasCap && projected !== null && (
                <>
                    <Tooltip title={breakdown}>
                        <QuotaMeterBar
                            usedPct={usedPct}
                            projected={[
                                { pct: othersPct, barClass: 'bg-accent' },
                                { pct: thisScannerPct, barClass: styles.bar, striped: true },
                            ]}
                            valueNow={percentLabel}
                            label={`Projected ${percentLabel}% of monthly observation quota by ${
                                resetsOn ?? 'period end'
                            }`}
                        />
                    </Tooltip>
                    <div className="flex items-center gap-3 text-xs text-muted">
                        <QuotaMeterLegendItem>Used</QuotaMeterLegendItem>
                        <QuotaMeterLegendItem barClass="bg-accent">Projected (other scanners)</QuotaMeterLegendItem>
                        <QuotaMeterLegendItem barClass={styles.bar} striped>
                            Projected (this scanner)
                        </QuotaMeterLegendItem>
                    </div>
                </>
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
                <div className="text-xs text-muted">
                    Based on{' '}
                    {scannerEstimate.matched_moments_in_window != null && (
                        <>
                            <strong>{scannerEstimate.matched_moments_in_window.toLocaleString()}</strong> moments
                            across{' '}
                        </>
                    )}
                    <strong>{scannerEstimate.matched_sessions_in_window.toLocaleString()}</strong> matching recordings
                    in the last {scannerEstimate.window_days} days.
                </div>
            ) : scannerEstimateError ? (
                <div className="text-xs text-danger">Couldn't estimate impact: {scannerEstimateError}</div>
            ) : (
                <div className="text-xs text-muted">Estimate unavailable. Try adjusting your filters.</div>
            )}
        </LemonCard>
    )
}
