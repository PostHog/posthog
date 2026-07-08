import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightLogicProps } from '~/types'

import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { QUOTA_STATUS_STYLES, projectQuota } from '../../utils/quotaProjection'
import { replayScannersLogic } from '../replayScannersLogic'
import { SCANNER_TYPE_OPTIONS } from '../types'
import { QuotaMeterBar, QuotaMeterLegendItem } from './QuotaMeterBar'
import { QuotaStatusLine } from './QuotaStatusLine'
import { VisionInsightChart } from './VisionInsightChart'

const RECORDING_OBSERVED_EVENT = '$recording_observed'
const COLLECTION_ID = 'replay-vision-list-observations'

export function VisionMetrics(): JSX.Element {
    const { scannerStats, chartDateFrom, chartDateTo } = useValues(replayScannersLogic)
    const { setChartDateRange } = useActions(replayScannersLogic)
    const { quota, quotaLoading } = useValues(visionQuotaLogic)

    const projection = projectQuota(quota)
    const { resetsOn, status, percentLabel, usedPct, projectedPct } = projection
    const hasCap = (quota?.monthly_quota ?? 0) > 0
    const styles = QUOTA_STATUS_STYLES[status]

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
        <div className="flex flex-col lg:flex-row gap-4 h-72">
            <div className="flex-1 bg-bg-light rounded p-4 flex flex-col InsightCard h-full">
                <div className="flex items-start justify-between gap-2 mb-1">
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
                        <div className="text-muted text-xs font-medium uppercase">Observations this month</div>
                        {hasCap && (
                            <span className={`text-xs tabular-nums ${styles.text}`}>
                                {percentLabel}%{' '}
                                <span className="text-muted font-normal">by {resetsOn ?? 'period end'}</span>
                            </span>
                        )}
                    </div>
                    {quota ? (
                        <>
                            <div className="text-3xl font-semibold tabular-nums">
                                {quota.usage_this_month.toLocaleString()}
                                <span className="text-muted text-lg font-normal">
                                    {' / '}
                                    {quota.monthly_quota.toLocaleString()}
                                </span>
                            </div>
                            <Tooltip
                                title={
                                    <div className="text-xs space-y-0.5">
                                        <div>
                                            Used this month: <strong>{quota.usage_this_month.toLocaleString()}</strong>
                                        </div>
                                        <div>
                                            Projected from enabled scanners:{' '}
                                            <strong>
                                                ~{quota.projected_monthly_observations.toLocaleString()}/month
                                            </strong>
                                        </div>
                                        <div>
                                            Monthly quota: <strong>{quota.monthly_quota.toLocaleString()}</strong>
                                        </div>
                                        {resetsOn && <div className="text-muted">Resets {resetsOn}</div>}
                                    </div>
                                }
                            >
                                <QuotaMeterBar
                                    className="mt-2"
                                    usedPct={usedPct}
                                    projected={[{ pct: projectedPct, barClass: styles.bar, striped: true }]}
                                    valueNow={percentLabel}
                                    label={`Projected ${percentLabel}% of monthly observation quota`}
                                />
                            </Tooltip>
                            <div className="flex items-center gap-3 text-xs text-muted mt-1.5">
                                <QuotaMeterLegendItem>Used</QuotaMeterLegendItem>
                                <QuotaMeterLegendItem barClass={styles.bar} striped>
                                    Projected
                                </QuotaMeterLegendItem>
                                <span className="ml-auto">
                                    <QuotaStatusLine projection={projection} />
                                </span>
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
