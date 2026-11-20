import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    EndpointsUsageTrendsQuery,
    EndpointsUsageTrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { IntervalType } from '~/types'

import {
    type EndpointsUsageMetric,
    type TrendsDataPoint,
    transformDataForChart,
} from './endpointsUsageTrendsTransforms'
import { QuillEndpointsUsageTrends } from './QuillEndpointsUsageTrends'

const handleChartError = makeChartErrorHandler('endpoints-usage-trends-chart')

let uniqueNode = 0
export function EndpointsUsageTrendsNode(props: {
    query: EndpointsUsageTrendsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `EndpointsUsageTrends.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    useAttachedLogic(logic, props.attachTo)

    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const queryResponse = response as EndpointsUsageTrendsQueryResponse | undefined
    const results = queryResponse?.results as TrendsDataPoint[] | undefined
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillEndpointsUsageTrends
                results={results}
                loading={responseLoading}
                error={responseError}
                onRetry={() => loadData()}
                metric={props.query.metric}
                interval={props.query.interval}
            />
        )
    }

    if (responseLoading) {
        return (
            <div className="border rounded bg-bg-light p-4 h-60">
                <LemonSkeleton className="w-full h-full" />
            </div>
        )
    }

    if (!results || results.length === 0) {
        return (
            <div className="flex items-center justify-center h-60 border rounded bg-bg-light text-muted">
                No data available for this period
            </div>
        )
    }

    return (
        <div className="border rounded bg-bg-light p-2">
            <EndpointsUsageTrendsChart results={results} metric={props.query.metric} interval={props.query.interval} />
        </div>
    )
}

export function EndpointsUsageTrendsChart({
    results,
    metric,
    // Quill only formats the axis ticks and the tooltip header when both `timezone` and `interval`
    // are set, so an absent interval would leave raw ISO labels on both.
    interval = 'day',
}: {
    results: TrendsDataPoint[]
    metric: EndpointsUsageMetric
    interval?: IntervalType
}): JSX.Element {
    const isAreaChart = metric === 'cpu_seconds' || metric === 'bytes_read'

    const { labels, series, scale } = useMemo(
        () => transformDataForChart(results, metric, isAreaChart),
        [results, metric, isAreaChart]
    )

    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const config = useChartConfig<TimeSeriesLineChartConfig>(() => {
        const formatValue = (value: number): string => `${value.toFixed(scale.decimalPlaces)}${scale.suffix}`
        return {
            xAxis: { timezone, interval, allDays: labels },
            yAxis: { scale: 'linear', showGrid: true, startAtZero: true, tickFormatter: formatValue },
            legend: { show: series.length > 1, position: 'top', interactive: true },
            tooltip: {
                placement: 'cursor',
                pinnable: true,
                sortedByValue: true,
                showTotal: series.length > 1,
                valueFormatter: formatValue,
            },
        }
    }, [labels, series.length, scale, timezone, interval])

    return (
        <div className="h-60 flex flex-col">
            <TimeSeriesLineChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                onError={handleChartError}
            />
        </div>
    )
}
