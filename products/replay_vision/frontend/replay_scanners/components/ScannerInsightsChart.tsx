import { useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useMemo } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { isNullBreakdown, isOtherBreakdown } from 'scenes/insights/utils'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, ProductKey, TrendsQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    InsightLogicProps,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import { scannerOverviewLogic } from '../scannerOverviewLogic'
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

/**
 * Search params for drilling from a chart data point into the Observations tab: the clicked day as an
 * inclusive date range, plus the clicked tag for classifier breakdown series. Returns null when the
 * clicked bucket isn't a plain date (nothing sensible to drill into).
 */
export function observationsDrilldownSearchParams(
    day: string | number | undefined,
    breakdown?: unknown
): Record<string, string> | null {
    if (typeof day !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(day)) {
        return null
    }
    const date = day.slice(0, 10)
    const params: Record<string, string> = { tab: 'observations', date_from: date, date_to: date }
    const tag = Array.isArray(breakdown) ? breakdown[0] : breakdown
    if (typeof tag === 'string' && tag && !isOtherBreakdown(tag) && !isNullBreakdown(tag)) {
        params.tags = tag
    }
    return params
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
    // Date comes from the Overview tab's shared filter bar (scannerOverviewLogic), so the chart and the
    // stat panels move together; the chart no longer carries its own date picker.
    const { overviewDateFrom, overviewDateTo, coverageStats, overviewStatsApiLoading } = useValues(
        scannerOverviewLogic({ scannerId })
    )
    // Memoized so a re-render (e.g. stats arriving) can't churn the query and abort an in-flight load.
    // `tags.productKey` is required for ClickHouse query tagging; without it the runner aborts.
    const chartQuery = useMemo<InsightVizNode>(
        () => ({
            kind: NodeKind.InsightVizNode,
            source: {
                ...buildQuery(scannerId, scannerType, overviewDateFrom, overviewDateTo),
                tags: { productKey: ProductKey.REPLAY_VISION },
            },
        }),
        [scannerId, scannerType, overviewDateFrom, overviewDateTo]
    )
    const chartInsightProps = useMemo<InsightLogicProps>(
        () => ({
            dashboardItemId: `new-replay-vision-scanner-${scannerId}-chart`,
            dataNodeCollectionId: COLLECTION_ID,
        }),
        [scannerId]
    )
    // Drill-down goes to the Observations tab filtered to the clicked day (and tag, for classifier series):
    // that's where each scanned session shows its verdict/tags/score, unlike the generic persons modal,
    // which can't represent these server-emitted events (see VisionInsightChart).
    const onDataPointClick = useCallback<NonNullable<QueryContext['onDataPointClick']>>(
        (series) => {
            const searchParams = observationsDrilldownSearchParams(series.day, series.breakdown)
            if (searchParams) {
                router.actions.push(urls.replayVision(scannerId), searchParams)
            }
        },
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
                    ) : overviewStatsApiLoading ? (
                        <div className="text-xs text-muted mt-0.5 flex items-center gap-1.5">
                            <Spinner /> Loading coverage…
                        </div>
                    ) : null}
                </div>
            </div>
            <VisionInsightChart
                query={chartQuery}
                insightProps={chartInsightProps}
                className="InsightCard h-80"
                onDataPointClick={onDataPointClick}
            />
        </div>
    )
}
