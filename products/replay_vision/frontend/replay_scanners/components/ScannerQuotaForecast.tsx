import { useValues } from 'kea'

import { LemonCard, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { NoBillingLimitNote } from '../../components/NoBillingLimitNote'
import { QuotaExhaustedNote } from '../../components/QuotaExhaustedNote'
import { QuotaImminentBanner } from '../../components/QuotaImminentBanner'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import {
    QUOTA_STATUS_STYLES,
    type QuotaStatus,
    daysUntilCapReached,
    hasCreditLimit,
    projectQuota,
    splitProjectedPct,
} from '../../utils/quotaProjection'
import { replayScannerLogic } from '../replayScannerLogic'
import { QUOTA_METER_FREE_CLASS, QuotaMeterBar, QuotaMeterLegendItem, quotaMeterWidths } from './QuotaMeterBar'
import { QuotaStatusLine } from './QuotaStatusLine'

interface Props {
    scannerId: string
}

export function ScannerQuotaForecast({ scannerId }: Props): JSX.Element | null {
    const { scanner, scannerEstimate, scannerEstimateLoading, scannerEstimateError } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const {
        displayQuota: quota,
        showUsd,
        onFreePlan,
        startupCapCredits,
        showStartupCapLine,
    } = useValues(visionQuotaLogic)

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
    const { status, percentLabel, resetsOn, usedPct, usedFreePct, projectedPct } = projection

    const effectiveStatus: QuotaStatus = projectedCredits === null ? 'safe' : status
    const styles = QUOTA_STATUS_STYLES[effectiveStatus]

    // No estimate means the projection isn't about the scanner being edited.
    const imminentDays = projectedCredits !== null ? daysUntilCapReached(projection) : null

    const { thisScannerPct, othersPct } = splitProjectedPct(projectedPct, projectedCredits ?? 0, othersMonthly)
    const [freeWidth, billedWidth, othersWidth, thisWidth] = quotaMeterWidths(usedPct, usedFreePct, [
        othersPct,
        thisScannerPct,
    ])

    const breakdown = (
        <div className="text-xs space-y-0.5">
            <div>
                Spent this period: <strong>{formatCreditCount(used)}</strong>
            </div>
            <div>
                Projected from this scanner: <strong>~{formatCreditCount(projectedCredits ?? 0)}/month</strong>
            </div>
            <div>
                Projected from other scanners: <strong>~{formatCreditCount(othersMonthly)}/month</strong>
            </div>
            {hasCap && (
                <div>
                    Monthly limit: <strong>{formatCreditCount(cap)}</strong>
                </div>
            )}
            {showStartupCapLine && (
                <div>
                    Startup program cap: <strong>{formatCreditCount(startupCapCredits ?? 0)}/month</strong>
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

            <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
                {projectedCredits !== null ? (
                    <div className="text-base font-semibold tabular-nums flex items-center gap-2">
                        <span>
                            ~{formatCreditCount(projectedCredits)}
                            <span className="text-sm font-normal text-muted">/month</span>{' '}
                            <span className="text-sm font-normal text-muted">
                                {showUsd ? `(≈ ${creditsToUsd(projectedCredits)}) · ` : ''}
                                {(projectedObservations ?? 0).toLocaleString()} observations at{' '}
                                {formatCreditCount(scannerEstimate?.credits_per_observation ?? 0)} each
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
                {/* The exhausted note and the imminent banner below carry this status, so don't say it twice. */}
                {hasCap && !projection.exhausted && imminentDays === null && (
                    <span className="text-xs tabular-nums">
                        <QuotaStatusLine projection={projection} onFreePlan={onFreePlan} />
                    </span>
                )}
            </div>

            {/* `hasCap` is also false while quota is still loading, so require a resolved snapshot before
                telling anyone their billing limit is missing. */}
            {quota !== null && !hasCap && projectedCredits !== null && (
                <Tooltip title={breakdown}>
                    <div>
                        <NoBillingLimitNote projectedCredits={newFleetMonthly} />
                    </div>
                </Tooltip>
            )}

            {hasCap && projection.exhausted && <QuotaExhaustedNote onFreePlan={onFreePlan} />}

            {imminentDays !== null && projection.capReachDate && (
                <QuotaImminentBanner capReachDate={projection.capReachDate} onFreePlan={onFreePlan} />
            )}

            {hasCap && projectedCredits !== null && (
                <>
                    <Tooltip title={breakdown}>
                        <QuotaMeterBar
                            usedPct={usedPct}
                            usedFreePct={usedFreePct}
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
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                        <QuotaMeterLegendItem barClass={QUOTA_METER_FREE_CLASS} width={freeWidth}>
                            Free
                        </QuotaMeterLegendItem>
                        <QuotaMeterLegendItem width={billedWidth}>
                            {freeWidth > 0 ? 'Billed' : 'Spent'}
                        </QuotaMeterLegendItem>
                        <QuotaMeterLegendItem barClass="bg-accent" width={othersWidth}>
                            Projected (other scanners)
                        </QuotaMeterLegendItem>
                        <QuotaMeterLegendItem barClass={styles.bar} striped width={thisWidth}>
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
