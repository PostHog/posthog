import { type ReactElement, useState } from 'react'

import { EmptyState } from '@posthog/mosaic'

import { BarChart, BigNumber, BoxPlotChart, type BoxPlotSeries, LineChart, Select, type Series } from './charts'
import type { BoxPlotDatum, TrendsResult, TrendsResultItem, TrendsVisualizerProps } from './types'
import { getDisplayType, getSeriesLabel, isBarChart, isBoxPlotResult } from './utils'

type ChartMode = 'line' | 'bar'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

function prepareChartData(results: TrendsResultItem[]): {
    series: Series[]
    labels: string[]
    maxValue: number
} {
    if (!results || results.length === 0) {
        return { series: [], labels: [], maxValue: 0 }
    }

    const labels = results[0]?.days || results[0]?.labels || []
    let maxValue = 0

    const series = results.map((item, seriesIndex) => {
        const data = item.data || []
        const points = data.map((value, i) => {
            maxValue = Math.max(maxValue, value)
            return {
                x: i,
                y: value,
                label: labels[i] || `${i}`,
            }
        })
        return {
            label: getSeriesLabel(item, seriesIndex),
            points,
        }
    })

    return { series, labels, maxValue: maxValue || 1 }
}

function prepareBoxPlotData(results: BoxPlotDatum[]): {
    series: BoxPlotSeries[]
    labels: string[]
    minValue: number
    maxValue: number
} {
    if (!results || results.length === 0) {
        return { series: [], labels: [], minValue: 0, maxValue: 0 }
    }

    const labelByDay = new Map<string, string>()
    const orderedDays: string[] = []
    const grouped = new Map<number, { label: string; seriesIndex: number; byDay: Map<string, BoxPlotDatum> }>()

    let minValue = Infinity
    let maxValue = -Infinity

    for (const datum of results) {
        if (!labelByDay.has(datum.day)) {
            labelByDay.set(datum.day, datum.label)
            orderedDays.push(datum.day)
        }
        const seriesIndex = datum.series_index ?? 0
        if (!grouped.has(seriesIndex)) {
            grouped.set(seriesIndex, {
                label: datum.series_label || `Series ${seriesIndex + 1}`,
                seriesIndex,
                byDay: new Map(),
            })
        }
        grouped.get(seriesIndex)!.byDay.set(datum.day, datum)
        minValue = Math.min(minValue, datum.min)
        maxValue = Math.max(maxValue, datum.max)
    }

    const labels = orderedDays.map((day) => labelByDay.get(day) || day)

    const series: BoxPlotSeries[] = Array.from(grouped.values())
        .sort((a, b) => a.seriesIndex - b.seriesIndex)
        .map(({ label, seriesIndex, byDay }) => ({
            label,
            seriesIndex,
            data: orderedDays.map(
                (day) =>
                    byDay.get(day) ?? {
                        day,
                        label: labelByDay.get(day) || day,
                        min: 0,
                        p25: 0,
                        median: 0,
                        p75: 0,
                        max: 0,
                        mean: 0,
                        series_index: seriesIndex,
                        series_label: label,
                    }
            ),
        }))

    if (!Number.isFinite(minValue)) {
        minValue = 0
    }
    if (!Number.isFinite(maxValue) || maxValue === minValue) {
        maxValue = minValue + 1
    }

    return { series, labels, minValue, maxValue }
}

function calculateTotal(results: TrendsResultItem[]): number {
    return results.reduce((sum, item) => {
        if (typeof item.aggregated_value === 'number') {
            return sum + item.aggregated_value
        }
        if (typeof item.count === 'number') {
            return sum + item.count
        }
        if (item.data && item.data.length > 0) {
            return sum + item.data.reduce((a, b) => a + b, 0)
        }
        return sum
    }, 0)
}

function isEmptyResults(results: TrendsResult): boolean {
    return !results || results.length === 0
}

export function TrendsVisualizer({ query, results }: TrendsVisualizerProps): ReactElement {
    const displayType = getDisplayType(query)
    const boxPlotIntent = displayType === 'BoxPlot' || isBoxPlotResult(results)
    const [chartMode, setChartMode] = useState<ChartMode>(isBarChart(displayType) ? 'bar' : 'line')

    if (isEmptyResults(results)) {
        return <EmptyState icon="chart" description="No data available" />
    }

    if (boxPlotIntent) {
        const boxData = prepareBoxPlotData(results as BoxPlotDatum[])
        if (boxData.series.length === 0) {
            return <EmptyState icon="chart" description="No data available" />
        }
        return (
            <BoxPlotChart
                series={boxData.series}
                labels={boxData.labels}
                minValue={boxData.minValue}
                maxValue={boxData.maxValue}
                yAxisLabel={boxData.series.length === 1 ? boxData.series[0]?.label : undefined}
            />
        )
    }

    const trendResults = results as TrendsResultItem[]
    const { series, labels, maxValue } = prepareChartData(trendResults)

    if (series.length === 0) {
        return <EmptyState icon="chart" description="No data available" />
    }

    if (displayType === 'BoldNumber') {
        const total = calculateTotal(trendResults)
        const label = trendResults[0] ? getSeriesLabel(trendResults[0], 0) : 'Total'
        return <BigNumber value={total} label={label} />
    }

    return (
        <div>
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    marginBottom: '0.5rem',
                }}
            >
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={chartMode} onChange={setChartMode} options={CHART_MODE_OPTIONS} />
            </div>
            {chartMode === 'bar' ? (
                <BarChart
                    series={series}
                    labels={labels}
                    maxValue={maxValue}
                    yAxisLabel={series.length === 1 ? series[0]?.label : undefined}
                />
            ) : (
                <LineChart
                    series={series}
                    labels={labels}
                    maxValue={maxValue}
                    yAxisLabel={series.length === 1 ? series[0]?.label : undefined}
                />
            )}
        </div>
    )
}
