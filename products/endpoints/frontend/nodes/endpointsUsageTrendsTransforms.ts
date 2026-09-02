import { type Series } from '@posthog/quill-charts'

import { EndpointsUsageTrendsQuery } from '~/queries/schema/schema-general'

export type EndpointsUsageMetric = EndpointsUsageTrendsQuery['metric']

export type TrendsDataPoint = {
    date: string
    value: number
    breakdown?: string
}

export interface ScaleFactor {
    divisor: number
    label: string
    suffix: string
    decimalPlaces: number
}

export function getScaleFactor(values: number[], metric: EndpointsUsageMetric): ScaleFactor {
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

export function transformDataForChart(
    results: TrendsDataPoint[],
    metric: EndpointsUsageMetric,
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

function getMetricLabel(metric: EndpointsUsageMetric): string {
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
