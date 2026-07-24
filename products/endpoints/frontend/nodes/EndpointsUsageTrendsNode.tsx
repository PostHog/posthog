import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
import {
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    createXAxisTickCallback,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    EndpointsUsageTrendsQuery,
    EndpointsUsageTrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

type TrendsDataPoint = {
    date: string
    value: number
    breakdown?: string
}

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

    const { response, responseLoading } = useValues(logic)
    const queryResponse = response as EndpointsUsageTrendsQueryResponse | undefined
    const results = queryResponse?.results as TrendsDataPoint[] | undefined

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

    return <EndpointsUsageTrendsChart results={results} metric={props.query.metric} />
}

export function EndpointsUsageTrendsChart({
    results,
    metric,
}: {
    results: TrendsDataPoint[]
    metric: string
}): JSX.Element {
    // CPU time and bytes read render better as filled areas; other metrics stay plain lines.
    const isAreaChart = metric === 'cpu_seconds' || metric === 'bytes_read'

    const { labels, series, scale } = useMemo(
        () => transformDataForChart(results, metric, isAreaChart),
        [results, metric, isAreaChart]
    )

    const theme = useChartTheme()
    const config = useChartConfig<TimeSeriesLineChartConfig>(() => {
        const formatValue = (value: number): string => `${value.toFixed(scale.decimalPlaces)}${scale.suffix}`
        return {
            xAxis: { tickFormatter: createXAxisTickCallback({ allDays: labels, timezone: 'UTC' }) },
            yAxis: { tickFormatter: formatValue },
            legend: { show: series.length > 1, position: 'top', interactive: true },
            tooltip: {
                placement: 'cursor',
                pinnable: true,
                sortedByValue: true,
                showTotal: series.length > 1,
                valueFormatter: formatValue,
                labelFormatter: (label: string) => dayjs(label).format('MMM D, YYYY'),
            },
        }
    }, [labels, series.length, scale])

    return (
        // Quill charts fill a flex parent, so the sized container must be a flex column.
        <div className="border rounded bg-bg-light p-2 h-60 flex flex-col">
            <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}

interface ScaleFactor {
    divisor: number
    label: string
    suffix: string
    decimalPlaces: number
}

function getScaleFactor(values: number[], metric: string): ScaleFactor {
    if (values.length === 0) {
        return { divisor: 1, label: getMetricLabel(metric), suffix: '', decimalPlaces: 0 }
    }

    const maxValue = Math.max(...values)

    if (metric === 'bytes_read') {
        if (maxValue >= 1024 * 1024 * 1024) {
            return { divisor: 1024 * 1024 * 1024, label: 'Bytes read (GB)', suffix: ' GB', decimalPlaces: 2 }
        } else if (maxValue >= 1024 * 1024) {
            return { divisor: 1024 * 1024, label: 'Bytes read (MB)', suffix: ' MB', decimalPlaces: 2 }
        } else if (maxValue >= 1024) {
            return { divisor: 1024, label: 'Bytes read (KB)', suffix: ' KB', decimalPlaces: 2 }
        }
        return { divisor: 1, label: 'Bytes read (B)', suffix: ' B', decimalPlaces: 0 }
    }

    if (metric === 'query_duration') {
        if (maxValue >= 60000) {
            return { divisor: 60000, label: 'Query duration (min)', suffix: ' min', decimalPlaces: 2 }
        } else if (maxValue >= 1000) {
            return { divisor: 1000, label: 'Query duration (s)', suffix: ' s', decimalPlaces: 2 }
        }
        return { divisor: 1, label: 'Query duration (ms)', suffix: ' ms', decimalPlaces: 0 }
    }

    if (metric === 'cpu_seconds') {
        if (maxValue >= 60) {
            return { divisor: 60, label: 'CPU time (min)', suffix: ' min', decimalPlaces: 2 }
        }
        return { divisor: 1, label: 'CPU time (s)', suffix: ' s', decimalPlaces: 2 }
    }

    if (metric === 'error_rate') {
        // Error rate comes as 0-1, display as percentage
        return { divisor: 0.01, label: 'Error rate (%)', suffix: '%', decimalPlaces: 2 }
    }

    return { divisor: 1, label: getMetricLabel(metric), suffix: '', decimalPlaces: 0 }
}

function transformDataForChart(
    results: TrendsDataPoint[],
    metric: string,
    isAreaChart: boolean
): {
    labels: string[]
    series: Series[]
    scale: ScaleFactor
} {
    const fill = isAreaChart ? { fill: { opacity: 0.5 } } : {}
    const hasBreakdown = results.some((r) => r.breakdown !== undefined)

    if (hasBreakdown) {
        // Group by breakdown value
        const breakdowns = [...new Set(results.map((r) => r.breakdown || 'unknown'))]

        // Group by date
        const dateGroups = results.reduce(
            (acc, point) => {
                const dateKey = point.date
                if (!acc[dateKey]) {
                    acc[dateKey] = {}
                }
                acc[dateKey][point.breakdown || 'unknown'] = point.value
                return acc
            },
            {} as Record<string, Record<string, number>>
        )

        const dates = Object.keys(dateGroups).sort()

        // Determine scale based on all values for consistency across breakdowns
        const scale = getScaleFactor(
            results.map((r) => r.value),
            metric
        )

        return {
            labels: dates,
            series: breakdowns.map((breakdown) => ({
                key: breakdown,
                label: breakdown,
                data: dates.map((date) => (dateGroups[date][breakdown] || 0) / scale.divisor),
                ...fill,
            })),
            scale,
        }
    }

    // Simple case - no breakdown
    const scale = getScaleFactor(
        results.map((r) => r.value),
        metric
    )

    return {
        labels: results.map((r) => r.date),
        series: [
            {
                key: metric,
                label: scale.label,
                data: results.map((r) => r.value / scale.divisor),
                ...fill,
            },
        ],
        scale,
    }
}

function getMetricLabel(metric: string): string {
    switch (metric) {
        case 'bytes_read':
            return 'Bytes read'
        case 'cpu_seconds':
            return 'CPU time'
        case 'query_duration':
            return 'Query duration'
        case 'error_rate':
            return 'Error rate'
        case 'requests':
        default:
            return 'Executions'
    }
}
