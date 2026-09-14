import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightLogicProps } from '~/types'

import { NoBillingLimitNote } from '../../components/NoBillingLimitNote'
import { QuotaExhaustedNote } from '../../components/QuotaExhaustedNote'
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import { buildQuotaMeter, fleetContributions } from '../../utils/quotaContributions'
import { QUOTA_STATUS_STYLES } from '../../utils/quotaProjection'
import { STARTUP_CAP_EXPLANATION } from '../../utils/startupCap'
import { replayScannersLogic } from '../replayScannersLogic'
import { SCANNER_TYPE_OPTIONS } from '../types'
import { QuotaMeter } from './QuotaMeterBar'
import { QuotaStatusLine } from './QuotaStatusLine'
import { VisionInsightChart } from './VisionInsightChart'

const RECORDING_OBSERVED_EVENT = '$recording_observed'
const COLLECTION_ID = 'replay-vision-list-observations'

export function VisionMetrics(): JSX.Element {
    const { scannerStats, chartDateFrom, chartDateTo } = useValues(replayScannersLogic)
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

    // Memoized so a re-render (e.g. stats/quota arriving) can't churn the query and abort an in-flight load.
    // `tags.productKey` is required for ClickHouse query tagging; without it the runner aborts.
    const chartQuery = useMemo<InsightVizNode>(
        () => ({
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: RECORDING_OBSERVED_EVENT,
                        math: BaseMathType.TotalCount,
                        name: 'Observations',
                    },
                ],
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                dateRange: { date_from: chartDateFrom, date_to: chartDateTo },
                interval: 'day',
                tags: { productKey: ProductKey.REPLAY_VISION },
            },
        }),
        [chartDateFrom, chartDateTo]
    )
    const chartInsightProps = useMemo<InsightLogicProps>(
        () => ({ dashboardItemId: 'new-replay-vision-list-observations-chart', dataNodeCollectionId: COLLECTION_ID }),
        []
    )

    return (
        <div className="flex flex-col lg:flex-row gap-4 lg:h-96">
            <div className="flex-1 bg-bg-light rounded p-4 flex flex-col InsightCard h-full min-h-80 lg:min-h-0">
                <div className="flex flex-wrap items-start justify-between gap-2 mb-1">
                    <h3 className="text-base font-semibold m-0">Observations over time</h3>
                    <DateFilter
                        dateFrom={chartDateFrom}
                        dateTo={chartDateTo}
                        onChange={(from, to) => setChartDateRange(from ?? null, to ?? null)}
                    />
                </div>
                <p className="text-muted text-xs mb-3">Across all scanners</p>
                <VisionInsightChart
                    query={chartQuery}
                    insightProps={chartInsightProps}
                    className="flex-1 flex flex-col min-h-0"
                />
            </div>

            <div className="flex flex-1 flex-col gap-4">
                <div className="flex-1 bg-bg-light border rounded p-4 flex flex-col">
                    <div className="text-muted text-xs font-medium uppercase mb-2">Enabled scanners</div>
                    <div className="text-3xl font-semibold">
                        {scannerStats?.enabled ?? 0}
                        <span className="text-muted text-lg font-normal">
                            {' / '}
                            {scannerStats?.total ?? 0}
                        </span>
                    </div>
                    <div className="flex flex-wrap gap-1.5 mt-3">
                        {SCANNER_TYPE_OPTIONS.map(({ value }) => {
                            const { enabled = 0, total = 0 } = scannerStats?.by_type?.[value] ?? {}
                            return (
                                <ScannerTypeBadge
                                    key={value}
                                    scannerType={value}
                                    variant={total > 0 ? 'default' : 'muted'}
                                    suffix={`${enabled}/${total}`}
                                />
                            )
                        })}
                    </div>
                </div>
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
