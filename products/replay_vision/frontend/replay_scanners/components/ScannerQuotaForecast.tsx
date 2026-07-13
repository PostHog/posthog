import { useValues } from 'kea'

import { LemonCard, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { formatCredits } from '../../utils/credits'
import {
    QUOTA_STATUS_STYLES,
    type QuotaStatus,
    hasCreditLimit,
    projectQuota,
    splitProjectedPct,
} from '../../utils/quotaProjection'
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
    // The estimate already applies the quality filter and sampling rate backend-side.
    const projectedObservations = scannerEstimate?.estimated_observations_per_month ?? null
    const projectedCredits = scannerEstimate?.estimated_credits_per_month ?? null
    const hasCap = hasCreditLimit(quota)
    const used = quota?.credits_used ?? 0
    const cap = quota?.credit_limit ?? 0

    // `other_enabled_scanners_monthly_credits` comes from the same estimate response as `projectedCredits`, so the
    // two are a consistent snapshot. Subtracting this scanner's stored estimate from the live fleet sum instead would
    // race the estimate-refresh cadence and double-count the scanner right after creating it.
    const fleetMonthly = quota?.projected_monthly_credits ?? 0
    const othersMonthly = scannerEstimate?.other_enabled_scanners_monthly_credits ?? 0
    // projectQuota wants a delta off the stored fleet total, so compute the new fleet total (others + this) and pass the difference.
    const newFleetMonthly = projectedCredits !== null ? othersMonthly + projectedCredits : fleetMonthly
    const projection = projectQuota(quota, newFleetMonthly - fleetMonthly)
    const { status, percentLabel, resetsOn, usedPct, projectedPct } = projection

    const effectiveStatus: QuotaStatus = projectedCredits === null ? 'safe' : status
    const styles = QUOTA_STATUS_STYLES[effectiveStatus]

    const { thisScannerPct, othersPct } = splitProjectedPct(projectedPct, projectedCredits ?? 0, othersMonthly)

    const breakdown = (
        <div className="text-xs space-y-0.5">
            <div>
                Spent this month: <strong>{formatCredits(used)}</strong>
            </div>
            <div>
                Projected from this scanner: <strong>~{formatCredits(projectedCredits ?? 0)}/month</strong>
            </div>
            <div>
                Projected from other scanners: <strong>~{formatCredits(othersMonthly)}/month</strong>
            </div>
            {hasCap && (
                <div>
                    Monthly limit: <strong>{formatCredits(cap)}</strong>
                </div>
            )}
            {resetsOn && <div className="text-muted">Resets {resetsOn}</div>}
        </div>
    )

    return (
        <LemonCard hoverEffect={false} className="p-3 space-y-2">
            <div className="flex items-baseline justify-between gap-3">
                <LemonLabel>Estimated cost</LemonLabel>
                {hasCap && projectedCredits !== null && (
                    <Tooltip title={breakdown}>
                        <span className={`text-xs tabular-nums ${styles.text}`}>
                            {percentLabel}%{' '}
                            <span className="text-muted font-normal">by {resetsOn ?? 'period end'}</span>
                        </span>
                    </Tooltip>
                )}
            </div>

            <div className="flex items-baseline justify-between gap-3">
                {projectedCredits !== null ? (
                    <div className="text-base font-semibold tabular-nums flex items-center gap-2">
                        <span>
                            ~{formatCredits(projectedCredits)}
                            <span className="text-sm font-normal text-muted">/month</span>{' '}
                            <span className="text-sm font-normal text-muted">
                                ({(projectedObservations ?? 0).toLocaleString()} observations at{' '}
                                {formatCredits(scannerEstimate?.credits_per_observation ?? 0)} each)
                            </span>
                        </span>
                        {scannerEstimateLoading && (
                            <Tooltip title="Recomputing with the latest filters, sampling rate, and model.">
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

            {hasCap && projectedCredits !== null && (
                <>
                    <Tooltip title={breakdown}>
                        <QuotaMeterBar
                            usedPct={usedPct}
                            projected={[
                                { pct: othersPct, barClass: 'bg-accent' },
                                { pct: thisScannerPct, barClass: styles.bar, striped: true },
                            ]}
                            valueNow={percentLabel}
                            label={`Projected ${percentLabel}% of the monthly spend limit by ${
                                resetsOn ?? 'period end'
                            }`}
                        />
                    </Tooltip>
                    <div className="flex items-center gap-3 text-xs text-muted">
                        <QuotaMeterLegendItem>Spent</QuotaMeterLegendItem>
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
                    Based on <strong>{scannerEstimate.matched_sessions_in_window.toLocaleString()}</strong> matching
                    recordings in the last {scannerEstimate.window_days} days.
                </div>
            ) : scannerEstimateError ? (
                <div className="text-xs text-danger">Couldn't estimate cost: {scannerEstimateError}</div>
            ) : (
                <div className="text-xs text-muted">Estimate unavailable. Try adjusting your filters.</div>
            )}
        </LemonCard>
    )
}
