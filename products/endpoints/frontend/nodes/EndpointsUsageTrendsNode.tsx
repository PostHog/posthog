import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { AxisSeries } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import {
    AnyResponseType,
    EndpointsUsageTrendsQuery,
    EndpointsUsageTrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

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

    if (responseLoading) {
        return (
            <div className="border rounded bg-bg-light p-4 h-60">
                <LemonSkeleton className="w-full h-full" />
            </div>
        )
    }

    const results = queryResponse?.results as TrendsDataPoint[] | undefined

    if (!results || results.length === 0) {
        return (
            <div className="flex items-center justify-center h-60 border rounded bg-bg-light text-muted">
                No data available for this period
            </div>
        )
    }

    const { xData, yData } = transformDataForLineGraph(results, props.query.metric)

    // Use area chart for CPU time and bytes read (sparkline-like), line chart for others
    const chartType =
        props.query.metric === 'cpu_seconds' || props.query.metric === 'bytes_read'
            ? ChartDisplayType.ActionsAreaGraph
            : ChartDisplayType.ActionsLineGraph

    return (
        <div className="border rounded bg-bg-light p-2 h-60">
            <LineGraph
                xData={xData}
                yData={yData}
                visualizationType={chartType}
                chartSettings={{
                    showLegend: yData.length > 1,
                }}
            />
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

function scaleMetricData(
    values: number[],
    metric: string
): {
    values: number[]
    label: string
    settings: { formatting: { suffix: string; decimalPlaces: number } }
} {
    const { divisor, label, suffix, decimalPlaces } = getScaleFactor(values, metric)
    return {
        values: values.map((v) => v / divisor),
        label,
        settings: { formatting: { suffix, decimalPlaces } },
    }
}

function transformDataForLineGraph(
    results: TrendsDataPoint[],
    metric: string
): {
    xData: AxisSeries<string>
    yData: AxisSeries<number>[]
} {
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
        const allValues = results.map((r) => r.value)
        const scaleFactor = getScaleFactor(allValues, metric)

        return {
            xData: {
                column: {
                    name: 'date',
                    type: { name: 'DATE', isNumerical: false },
                    label: 'Date',
                    dataIndex: 0,
                },
                data: dates.map(formatDate),
            },
            yData: breakdowns.map((breakdown, index) => {
                const breakdownValues = dates.map((date) => dateGroups[date][breakdown] || 0)
                return {
                    column: {
                        name: breakdown,
                        type: { name: 'FLOAT', isNumerical: true },
                        label: breakdown,
                        dataIndex: index + 1,
                    },
                    data: breakdownValues.map((v) => v / scaleFactor.divisor),
                    settings: {
                        formatting: {
                            suffix: scaleFactor.suffix,
                            decimalPlaces: scaleFactor.decimalPlaces,
                        },
                    },
                }
            }),
        }
    }

    // Simple case - no breakdown
    const rawValues = results.map((r) => r.value)
    const { values: scaledValues, label: scaledLabel, settings } = scaleMetricData(rawValues, metric)

    return {
        xData: {
            column: {
                name: 'date',
                type: { name: 'DATE', isNumerical: false },
                label: 'Date',
                dataIndex: 0,
            },
            data: results.map((r) => formatDate(r.date)),
        },
        yData: [
            {
                column: {
                    name: metric,
                    type: { name: 'FLOAT', isNumerical: true },
                    label: scaledLabel,
                    dataIndex: 1,
                },
                data: scaledValues,
                settings,
            },
        ],
    }
}

function formatDate(dateStr: string): string {
    try {
        const date = new Date(dateStr)
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    } catch {
        return dateStr
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
