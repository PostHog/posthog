import { useActions, useValues } from 'kea'

import { Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { NoBillingLimitNote } from '../../components/NoBillingLimitNote'
import { QuotaExhaustedNote } from '../../components/QuotaExhaustedNote'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import { buildQuotaMeter, fleetContributions } from '../../utils/quotaContributions'
import { QUOTA_STATUS_STYLES } from '../../utils/quotaProjection'
import { STARTUP_CAP_EXPLANATION } from '../../utils/startupCap'
import { replayScannersLogic } from '../replayScannersLogic'
import { EnabledScannersCard } from './EnabledScannersCard'
import { ObservationsOverTimeCard } from './ObservationsOverTimeCard'
import { QuotaMeter } from './QuotaMeterBar'
import { QuotaStatusLine } from './QuotaStatusLine'

export function VisionMetrics(): JSX.Element {
    const { chartDateFrom, chartDateTo } = useValues(replayScannersLogic)
    const { setChartDateRange } = useActions(replayScannersLogic)
    const {
        displayQuota: quota,
        quotaLoading,
        showUsd,
        onFreePlan,
        billedCredits,
        billedLimitCredits,
        startupCapCredits,
        showStartupCap,
        showStartupCapLine,
    } = useValues(visionQuotaLogic)

    // Backfills are charged once, so they can't ride in the pro-rated projection; the model keeps them apart.
    const model = buildQuotaMeter(quota, fleetContributions(quota))
    const { projection, periodEndPct, hasCap, status } = model
    const styles = QUOTA_STATUS_STYLES[status]
    const { resetsOn } = projection

    return (
        <div className="flex flex-col lg:flex-row gap-4 lg:h-96">
            <ObservationsOverTimeCard
                dateFrom={chartDateFrom}
                dateTo={chartDateTo}
                onDateChange={setChartDateRange}
                className="flex-1 h-full min-h-80 lg:min-h-0"
            />

            <div className="flex flex-1 flex-col gap-4">
                <EnabledScannersCard className="flex-1" />
                <div className="flex-1 bg-bg-light border rounded p-4 flex flex-col">
                    <div className="flex items-baseline justify-between gap-3 mb-2">
                        <div className="text-muted text-xs font-medium uppercase">Spend this billing period</div>
                        {hasCap && (
                            <span className={`text-xs tabular-nums ${styles.text}`}>
                                {periodEndPct}%{' '}
                                <span className="text-muted font-normal">
                                    by period end{resetsOn ? ` (${resetsOn})` : ''}
                                </span>
                            </span>
                        )}
                    </div>
                    {quota ? (
                        <>
                            <div className="text-3xl font-semibold tabular-nums">
                                {formatCreditCount(quota.credits_used)}
                                {hasCap && (
                                    <span className="text-muted text-lg font-normal">
                                        {' / '}
                                        {formatCreditCount(quota.credit_limit ?? 0)}
                                    </span>
                                )}
                            </div>
                            {showUsd && (
                                <div className="text-muted text-sm tabular-nums">
                                    ≈ {creditsToUsd(billedCredits)} billed
                                    {hasCap ? ` / ${creditsToUsd(billedLimitCredits)} limit` : ''}
                                </div>
                            )}
                            {hasCap ? (
                                <>
                                    <Tooltip
                                        title={
                                            <div className="text-xs space-y-0.5">
                                                <div>
                                                    Spent this billing period:{' '}
                                                    <strong>{formatCreditCount(quota.credits_used)}</strong>
                                                </div>
                                                <div>
                                                    Projected from enabled scanners:{' '}
                                                    <strong>
                                                        ~{formatCreditCount(quota.projected_monthly_credits)}/month
                                                    </strong>
                                                </div>
                                                <div>
                                                    Monthly limit:{' '}
                                                    <strong>{formatCreditCount(quota.credit_limit ?? 0)}</strong>
                                                </div>
                                                {showStartupCapLine && (
                                                    <div>
                                                        Startup program cap:{' '}
                                                        <strong>
                                                            {formatCreditCount(startupCapCredits ?? 0)}/month
                                                        </strong>
                                                    </div>
                                                )}
                                                {resetsOn && <div className="text-muted">Resets {resetsOn}</div>}
                                            </div>
                                        }
                                    >
                                        <QuotaMeter
                                            model={model}
                                            className="mt-2"
                                            label={`Projected ${periodEndPct}% of the monthly spend limit`}
                                        />
                                    </Tooltip>
                                    {/* The exhausted note below carries this status, so don't say it twice. */}
                                    {!projection.exhausted && (
                                        <div className="text-xs text-muted mt-1.5">
                                            <QuotaStatusLine projection={projection} onFreePlan={onFreePlan} />
                                        </div>
                                    )}
                                    {projection.exhausted && (
                                        <div className="mt-1.5">
                                            <QuotaExhaustedNote onFreePlan={onFreePlan} />
                                        </div>
                                    )}
                                </>
                            ) : (
                                <div className="mt-2">
                                    <NoBillingLimitNote projectedCredits={quota.projected_monthly_credits} />
                                </div>
                            )}
                            {showStartupCap && (
                                <div className="text-xs text-muted mt-1.5">{STARTUP_CAP_EXPLANATION}</div>
                            )}
                            <div className="mt-2">
                                <Link to={`${urls.replayVision()}?tab=usage`} className="text-xs">
                                    View usage by scanner
                                </Link>
                            </div>
                        </>
                    ) : quotaLoading ? (
                        <div className="flex items-center py-2">
                            <Spinner />
                        </div>
                    ) : (
                        <div className="text-3xl font-semibold">—</div>
                    )}
                </div>
            </div>
        </div>
    )
}
