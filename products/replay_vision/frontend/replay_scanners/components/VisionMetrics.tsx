import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, ProductKey, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { replayScannersLogic } from '../replayScannersLogic'
import { SCANNER_TYPE_OPTIONS, SCANNER_TYPE_TAG_TYPE, scannerTypeLabel } from '../types'

const RECORDING_OBSERVED_EVENT = '$recording_observed'
const COLLECTION_ID = 'replay-vision-list-observations'

export function VisionMetrics(): JSX.Element {
    const { scannerStats, chartDateFrom, chartDateTo } = useValues(replayScannersLogic)
    const { setChartDateRange } = useActions(replayScannersLogic)
    const { quota } = useValues(visionQuotaLogic)

    const ratio = quota && quota.monthly_quota > 0 ? Math.min(quota.usage_this_month / quota.monthly_quota, 1) : 0
    const quotaStroke = quota?.exhausted ? 'var(--danger)' : ratio >= 0.8 ? 'var(--warning)' : 'var(--success)'

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
                            <LemonProgress
                                className="mt-2"
                                percent={Math.round(ratio * 100)}
                                strokeColor={quotaStroke}
                            />
                            <div className="text-muted text-sm mt-1">
                                {quota.exhausted ? (
                                    <span className="text-danger">Quota reached</span>
                                ) : (
                                    `${quota.remaining.toLocaleString()} remaining`
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
