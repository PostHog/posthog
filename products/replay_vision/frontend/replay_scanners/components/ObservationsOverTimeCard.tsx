import { useMemo } from 'react'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { cn } from 'lib/utils/css-classes'

import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightLogicProps } from '~/types'

import { VisionInsightChart } from './VisionInsightChart'

const RECORDING_OBSERVED_EVENT = '$recording_observed'
const COLLECTION_ID = 'replay-vision-list-observations'

interface ObservationsOverTimeCardProps {
    dateFrom: string | null
    dateTo: string | null
    onDateChange: (dateFrom: string | null, dateTo: string | null) => void
    className?: string
}

export function ObservationsOverTimeCard({
    dateFrom,
    dateTo,
    onDateChange,
    className,
}: ObservationsOverTimeCardProps): JSX.Element {
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
                dateRange: { date_from: dateFrom, date_to: dateTo },
                interval: 'day',
                tags: { productKey: ProductKey.REPLAY_VISION },
            },
        }),
        [dateFrom, dateTo]
    )
    const chartInsightProps = useMemo<InsightLogicProps>(
        () => ({ dashboardItemId: 'new-replay-vision-list-observations-chart', dataNodeCollectionId: COLLECTION_ID }),
        []
    )

    return (
        <div className={cn('bg-bg-light rounded p-4 flex flex-col InsightCard', className)}>
            <div className="flex flex-wrap items-start justify-between gap-2 mb-1">
                <h3 className="text-base font-semibold m-0">Observations over time</h3>
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(from, to) => onDateChange(from ?? null, to ?? null)}
                />
            </div>
            <p className="text-muted text-xs mb-3">Across all scanners</p>
            <VisionInsightChart
                query={chartQuery}
                insightProps={chartInsightProps}
                className="flex-1 flex flex-col min-h-0"
            />
        </div>
    )
}
