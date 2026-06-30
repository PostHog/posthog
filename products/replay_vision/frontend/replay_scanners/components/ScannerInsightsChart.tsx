import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { InsightVizNode, NodeKind, ProductKey, TrendsQuery } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    InsightLogicProps,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerType } from '../types'
import { VisionInsightChart } from './VisionInsightChart'

const RECORDING_OBSERVED_EVENT = '$recording_observed'
const COLLECTION_ID = 'replay-vision-scanner-insights'

function scannerIdFilter(scannerId: string): AnyPropertyFilter {
    return {
        type: PropertyFilterType.Event,
        key: 'scanner_id',
        operator: PropertyOperator.Exact,
        value: scannerId,
    }
}

function buildQuery(
    scannerId: string,
    scannerType: ScannerType,
    dateFrom: string | null,
    dateTo: string | null
): TrendsQuery {
    const base = scannerIdFilter(scannerId)
    const dateRange = { date_from: dateFrom, date_to: dateTo }
    if (scannerType === 'monitor') {
        return {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: RECORDING_OBSERVED_EVENT,
                    math: BaseMathType.TotalCount,
                    name: 'Yes verdicts',
                    properties: [
                        base,
                        {
                            type: PropertyFilterType.Event,
                            key: 'scanner_output_verdict',
                            operator: PropertyOperator.Exact,
                            value: 'yes',
                        },
                    ],
                },
                {
                    kind: NodeKind.EventsNode,
                    event: RECORDING_OBSERVED_EVENT,
                    math: BaseMathType.TotalCount,
                    name: 'Total observations',
                    properties: [base],
                },
            ],
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                formulaNodes: [{ formula: 'A / B * 100', custom_name: 'Yes rate' }],
            },
            dateRange,
            interval: 'day',
        }
    }
    if (scannerType === 'classifier') {
        return {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: RECORDING_OBSERVED_EVENT,
                    math: BaseMathType.TotalCount,
                    name: 'Observations',
                    properties: [base],
                },
            ],
            breakdownFilter: {
                // Union fixed + freeform tags; arrayJoin gives each tag its own series.
                breakdown:
                    "arrayJoin(arrayConcat(JSONExtract(ifNull(properties.scanner_output_tags, '[]'), 'Array(String)'), JSONExtract(ifNull(properties.scanner_output_tags_freeform, '[]'), 'Array(String)')))",
                breakdown_type: 'hogql',
            },
            trendsFilter: { display: ChartDisplayType.ActionsAreaGraph },
            dateRange,
            interval: 'day',
        }
    }
    if (scannerType === 'scorer') {
        const scoreSeries = (math: PropertyMathType): TrendsQuery['series'][number] => ({
            kind: NodeKind.EventsNode,
            event: RECORDING_OBSERVED_EVENT,
            math,
            math_property: 'scanner_output_score',
            properties: [base],
        })
        return {
            kind: NodeKind.TrendsQuery,
            series: [
                scoreSeries(PropertyMathType.Median),
                scoreSeries(PropertyMathType.P90),
                scoreSeries(PropertyMathType.Average),
            ],
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            dateRange,
            interval: 'day',
        }
    }
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: RECORDING_OBSERVED_EVENT,
                math: BaseMathType.TotalCount,
                name: 'Observations',
                properties: [base],
            },
        ],
        trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        dateRange,
        interval: 'day',
    }
}

function chartTitle(scannerType: ScannerType): string {
    if (scannerType === 'monitor') {
        return 'Yes rate (%) over time'
    }
    if (scannerType === 'classifier') {
        return 'Tag mix over time'
    }
    if (scannerType === 'scorer') {
        return 'Score percentiles over time'
    }
    return 'Observations over time'
}

export function ScannerInsightsChart({
    scannerId,
    scannerType,
}: {
    scannerId: string
    scannerType: ScannerType
}): JSX.Element {
    const { chartDateFrom, chartDateTo, coverageStats, observationStatsApiLoading } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const { setChartDateRange } = useActions(replayScannerLogic({ id: scannerId }))
    // Memoized so a re-render (e.g. stats arriving) can't churn the query and abort an in-flight load.
    // `tags.productKey` is required for ClickHouse query tagging; without it the runner aborts.
    const chartQuery = useMemo<InsightVizNode>(
        () => ({
            kind: NodeKind.InsightVizNode,
            source: {
                ...buildQuery(scannerId, scannerType, chartDateFrom, chartDateTo),
                tags: { productKey: ProductKey.REPLAY_VISION },
            },
        }),
        [scannerId, scannerType, chartDateFrom, chartDateTo]
    )
    const chartInsightProps = useMemo<InsightLogicProps>(
        () => ({
            dashboardItemId: `new-replay-vision-scanner-${scannerId}-chart`,
            dataNodeCollectionId: COLLECTION_ID,
        }),
        [scannerId]
    )
    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div className="flex items-baseline justify-between gap-2">
                <div>
                    <div className="text-sm font-medium">{chartTitle(scannerType)}</div>
                    {coverageStats.totalSessions > 0 ? (
                        <div className="text-xs text-muted tabular-nums mt-0.5">
                            Scanned <span className="font-semibold text-default">{coverageStats.recentSessions}</span>{' '}
                            session
                            {coverageStats.recentSessions === 1 ? '' : 's'} in the last {coverageStats.recentDays} day
                            {coverageStats.recentDays === 1 ? '' : 's'} ·{' '}
                            <span className="font-semibold text-default">{coverageStats.totalSessions}</span> total
                        </div>
                    ) : observationStatsApiLoading ? (
                        <div className="text-xs text-muted mt-0.5 flex items-center gap-1.5">
                            <Spinner /> Loading coverage…
                        </div>
                    ) : null}
                </div>
                <DateFilter
                    dateFrom={chartDateFrom}
                    dateTo={chartDateTo}
                    onChange={(from, to) => setChartDateRange(from ?? null, to ?? null)}
                />
            </div>
            <VisionInsightChart query={chartQuery} insightProps={chartInsightProps} className="InsightCard h-80" />
        </div>
    )
}
