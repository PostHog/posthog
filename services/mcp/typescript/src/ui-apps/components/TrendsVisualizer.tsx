import { type ReactElement, useState } from 'react'

import { BarChart, BigNumber, LineChart, Select, type Series } from './charts'
import type { TrendsResultItem, TrendsVisualizerProps } from './types'
import { getDisplayType, getSeriesLabel, isBarChart } from './utils'

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

    const labels = results[0]?.labels || results[0]?.days || []
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

function calculateTotal(results: TrendsResultItem[]): number {
    return results.reduce((sum, item) => {
        if (typeof item.count === 'number') {
            return sum + item.count
        }
        if (item.data && item.data.length > 0) {
            return sum + item.data.reduce((a, b) => a + b, 0)
        }
        return sum
    }, 0)
}

export function TrendsVisualizer({ query, results }: TrendsVisualizerProps): ReactElement {
    const displayType = getDisplayType(query)
    const [chartMode, setChartMode] = useState<ChartMode>(isBarChart(displayType) ? 'bar' : 'line')
    const { series, labels, maxValue } = prepareChartData(results)

    if (!results || results.length === 0 || series.length === 0) {
        return (
            <div
                style={{
                    padding: '2rem',
                    textAlign: 'center',
                    color: 'var(--color-text-secondary, #6b7280)',
                }}
            >
                No data available
            </div>
        )
    }

    if (displayType === 'BoldNumber') {
        const total = calculateTotal(results)
        const label = results[0] ? getSeriesLabel(results[0], 0) : 'Total'
        return <BigNumber value={total} label={label} />
    }

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.5rem' }}>
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={chartMode} onChange={setChartMode} options={CHART_MODE_OPTIONS} />
            </div>
            {chartMode === 'bar' ? (
                <BarChart series={series} labels={labels} maxValue={maxValue} />
            ) : (
                <LineChart series={series} labels={labels} maxValue={maxValue} />
            )}
        </div>
    )
}
