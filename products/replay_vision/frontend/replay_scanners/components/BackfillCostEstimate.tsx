import { useValues } from 'kea'

import { LemonBanner, LemonCard, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import type { BackfillEstimateResponseApi } from '../../generated/api.schemas'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import {
    QUOTA_STATUS_STYLES,
    QUOTA_WARN_THRESHOLD,
    type QuotaStatus,
    hasCreditLimit,
    projectQuota,
} from '../../utils/quotaProjection'
import {
    QUOTA_METER_BACKFILL_CLASS,
    QUOTA_METER_FREE_CLASS,
    QuotaMeterBar,
    QuotaMeterLegendItem,
    quotaMeterWidths,
} from './QuotaMeterBar'

interface Props {
    estimate: BackfillEstimateResponseApi | null
    loading: boolean
}

/**
 * The scanner editor's cost meter, re-pointed at a one-off backfill.
 *
 * `projectQuota` is reused for the recurring part only. Its delta argument is a *monthly rate* that it
 * pro-rates across the days left in the period, which would shrink a backfill's cost to a fraction of
 * itself. A backfill is charged once, so it is added at full value as its own segment on top.
 */
export function BackfillCostEstimate({ estimate, loading }: Props): JSX.Element {
    const { displayQuota: quota, showUsd, onFreePlan } = useValues(visionQuotaLogic)

    // Rendered even with no estimate yet, showing the period as it already stands. Picking a range
    // then adds a segment to the existing bar instead of making a whole card appear.
    const backfillCredits = estimate?.total_credits ?? 0
    const projection = projectQuota(quota)
    const hasCap = hasCreditLimit(quota)
    const cap = quota?.credit_limit ?? 0
    const used = quota?.credits_used ?? 0

    // Everything already committed for this period, plus what this backfill would add on top.
    const backfillPct = hasCap && cap > 0 ? (backfillCredits / cap) * 100 : 0
    const endOfPeriodPct = projection.usedPct + projection.projectedPct + backfillPct
    const status: QuotaStatus =
        endOfPeriodPct >= 100 ? 'danger' : endOfPeriodPct >= QUOTA_WARN_THRESHOLD * 100 ? 'warning' : 'safe'
    const styles = QUOTA_STATUS_STYLES[status]

    // Backfill sits ahead of the scanner projection: segments absorb overflow left to right, and a backfill is a
    // one-off charge that lands when it runs, so it keeps its width and the rest-of-period forecast gets truncated.
    const [freeWidth, billedWidth, backfillWidth, ongoingWidth] = quotaMeterWidths(
        projection.usedPct,
        projection.usedFreePct,
        [backfillPct, projection.projectedPct]
    )

    const breakdown = (
        <div className="text-xs space-y-0.5">
            <div>
                Spent this period: <strong>{formatCreditCount(used)}</strong>
            </div>
            <div>
                Projected from scanners:{' '}
                <strong>~{formatCreditCount(quota?.projected_monthly_credits ?? 0)}/month</strong>
            </div>
            {estimate && (
                <div>
                    This backfill: <strong>at most {formatCreditCount(backfillCredits)}</strong>
                </div>
            )}
            {hasCap && (
                <div>
                    Monthly limit: <strong>{formatCreditCount(cap)}</strong>
                </div>
            )}
            {projection.resetsOn && <div className="text-muted">Resets {projection.resetsOn}</div>}
        </div>
    )

    const overQuota =
        estimate !== null && estimate.credits_remaining !== null && backfillCredits > estimate.credits_remaining

    return (
        <LemonCard hoverEffect={false} className="p-3 space-y-2">
            <div className="flex items-baseline justify-between gap-3">
                <LemonLabel>Estimated cost</LemonLabel>
                {hasCap && (
                    <Tooltip title={breakdown}>
                        <span className={`text-xs tabular-nums ${styles.text}`}>
                            {Math.round(endOfPeriodPct)}%{' '}
                            <span className="text-muted font-normal">by {projection.resetsOn ?? 'period end'}</span>
                        </span>
                    </Tooltip>
                )}
            </div>

            <div className="text-base font-semibold tabular-nums flex items-center gap-2">
                {estimate ? (
                    <span>
                        at most {formatCreditCount(backfillCredits)}
                        <span className="text-sm font-normal text-muted">
                            {showUsd ? ` (≈ ${creditsToUsd(backfillCredits)})` : ''} ·{' '}
                            {estimate.total_sessions.toLocaleString()}{' '}
                            {estimate.total_sessions === 1 ? 'recording' : 'recordings'} at{' '}
                            {formatCreditCount(estimate.credits_per_observation)} each
                        </span>
                    </span>
                ) : (
                    <span className="text-sm font-normal text-muted">
                        {loading ? 'Counting recordings…' : 'Pick a time range to see the cost'}
                    </span>
                )}
                {loading && estimate && (
                    <Tooltip title="Recounting for the range you picked.">
                        <Spinner className="text-muted text-sm" />
                    </Tooltip>
                )}
            </div>

            {hasCap && (
                <>
                    <Tooltip title={breakdown}>
                        <QuotaMeterBar
                            usedPct={projection.usedPct}
                            usedFreePct={projection.usedFreePct}
                            projected={[
                                { pct: backfillPct, barClass: QUOTA_METER_BACKFILL_CLASS },
                                { pct: projection.projectedPct, barClass: 'bg-danger', striped: true },
                            ]}
                            valueNow={Math.round(endOfPeriodPct)}
                            label={`This backfill would take the period to ${Math.round(endOfPeriodPct)}% of the monthly spend limit`}
                        />
                    </Tooltip>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                        <QuotaMeterLegendItem barClass={QUOTA_METER_FREE_CLASS} width={freeWidth}>
                            Free
                        </QuotaMeterLegendItem>
                        <QuotaMeterLegendItem width={billedWidth}>
                            {freeWidth > 0 ? 'Billed' : 'Spent'}
                        </QuotaMeterLegendItem>
                        {estimate && (
                            <QuotaMeterLegendItem barClass={QUOTA_METER_BACKFILL_CLASS} width={backfillWidth}>
                                This backfill
                            </QuotaMeterLegendItem>
                        )}
                        <QuotaMeterLegendItem barClass="bg-danger" striped width={ongoingWidth}>
                            Projected (scanners)
                        </QuotaMeterLegendItem>
                    </div>
                </>
            )}

            {overQuota && (
                <LemonBanner type="warning">
                    This backfill costs more than your remaining credits{onFreePlan ? ' on the free plan' : ''}. It
                    scans the most recent recordings first, pauses when the quota runs out, and you can resume it next
                    period.
                </LemonBanner>
            )}
        </LemonCard>
    )
}
