import { useActions, useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, ProductKey, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { projectQuota } from '../../utils/quotaProjection'
import { replayScannersLogic } from '../replayScannersLogic'
import { SCANNER_TYPE_OPTIONS, SCANNER_TYPE_TAG_TYPE, scannerTypeLabel } from '../types'

const RECORDING_OBSERVED_EVENT = '$recording_observed'
const COLLECTION_ID = 'replay-vision-list-observations'

export function VisionMetrics(): JSX.Element {
    const { scannerStats, chartDateFrom, chartDateTo } = useValues(replayScannersLogic)
    const { setChartDateRange } = useActions(replayScannersLogic)
    const { quota } = useValues(visionQuotaLogic)

    const projection = projectQuota(quota)
    const { resetsOn, status, daysRemaining, combinedDailyRate } = projection
    const used = quota?.usage_this_month ?? 0
    const cap = quota?.monthly_quota ?? 0
    const hasCap = cap > 0
    const usedPct = hasCap ? Math.min((used / cap) * 100, 100) : 0
    const additionalUsagePct = hasCap ? Math.min((combinedDailyRate * daysRemaining * 100) / cap, 100 - usedPct) : 0
    const projectedBarColor = status === 'danger' ? 'bg-danger' : status === 'warning' ? 'bg-warning' : 'bg-success'

    // `tags.productKey` is required for ClickHouse query tagging; without it the runner aborts.
    const chartSource: TrendsQuery = {
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
    }

    return (
        <div className="flex gap-4 h-96">
            <div className="flex-1 bg-bg-light rounded p-4 flex flex-col InsightCard h-full">
                <div className="flex items-start justify-between gap-2 mb-1">
                    <h3 className="text-lg font-semibold m-0">Observations over time</h3>
                    <DateFilter
                        dateFrom={chartDateFrom}
                        dateTo={chartDateTo}
                        onChange={(from, to) => setChartDateRange(from ?? null, to ?? null)}
                    />
                </div>
                <p className="text-muted text-sm mb-4">Total scanner observations across all scanners</p>
                <div className="flex-1 flex flex-col min-h-0">
                    <Query
                        query={{ kind: NodeKind.InsightVizNode, source: chartSource } as InsightVizNode}
                        readOnly
                        embedded
                        inSharedMode
                        context={{
                            insightProps: {
                                dashboardItemId: 'new-replay-vision-list-observations-chart',
                                dataNodeCollectionId: COLLECTION_ID,
                            },
                        }}
                    />
                </div>
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
                                <LemonTag key={value} type={total > 0 ? SCANNER_TYPE_TAG_TYPE[value] : 'muted'}>
                                    {scannerTypeLabel(value)} {enabled}/{total}
                                </LemonTag>
                            )
                        })}
                    </div>
                </div>
                <div className="flex-1 bg-bg-light border rounded p-4 flex flex-col">
                    <div className="text-muted text-xs font-medium uppercase mb-2">Observations this month</div>
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
                                            Monthly quota: <strong>{quota.monthly_quota.toLocaleString()}</strong>
                                        </div>
                                        {resetsOn && <div className="text-muted">Resets {resetsOn}</div>}
                                    </div>
                                }
                            >
                                <div
                                    className="flex h-3 rounded overflow-hidden bg-fill-tertiary mt-2"
                                    role="meter"
                                    aria-valuemin={0}
                                    aria-valuemax={100}
                                    aria-valuenow={Math.round(usedPct + additionalUsagePct)}
                                    aria-label={`${Math.round(usedPct + additionalUsagePct)}% of monthly observation quota`}
                                >
                                    <div className="bg-muted" style={{ width: `${usedPct}%` }} />
                                    <div
                                        className={projectedBarColor}
                                        style={{
                                            width: `${additionalUsagePct}%`,
                                            backgroundImage:
                                                'repeating-linear-gradient(135deg, rgba(255,255,255,0.25) 0, rgba(255,255,255,0.25) 4px, transparent 4px, transparent 8px)',
                                        }}
                                    />
                                </div>
                            </Tooltip>
                            <div className="text-muted text-sm mt-1">
                                {quota.exhausted ? (
                                    <span className="text-danger">Quota exhausted</span>
                                ) : (
                                    `${quota.remaining.toLocaleString()} observations remaining.`
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="text-3xl font-semibold">—</div>
                    )}
                </div>
            </div>
        </div>
    )
}
