import { type ReactElement } from 'react'

import {
    type ChartTheme,
    type Series as ChartSeries,
    type YAxisFormat,
    TimeSeriesBarChart,
} from '@posthog/quill-charts'

import { formatDate } from '../utils'

// Series palette mirroring base.css `--posthog-chart-*`. Canvas can't read CSS
// custom properties, so we hand the chart concrete hexes. The chart picks one
// per series by index; the legend uses the same array to stay in sync.
const CHART_COLORS = ['#1d4aff', '#621da6', '#42827e', '#ce0e74', '#f14f58', '#7c440e', '#529a0a', '#0476fb']

const THEME: ChartTheme = { colors: CHART_COLORS }

export interface DataPoint {
    x: number
    y: number
    label: string
}

export interface Series {
    label: string
    points: DataPoint[]
}

export interface BarChartProps {
    series: Series[]
    labels: string[]
    maxValue: number
    showLegend?: boolean
    yAxisLabel?: string | undefined
    /** Y-axis value format. Mirrors a trends insight's `aggregationAxisFormat`; defaults to `numeric`. */
    yAxisFormat?: YAxisFormat | undefined
}

export function BarChart({
    series,
    labels,
    showLegend = true,
    yAxisLabel,
    yAxisFormat = 'numeric',
}: BarChartProps): ReactElement {
    // Color omitted so the chart assigns one per series from THEME.colors by index.
    const chartSeries: ChartSeries[] = series.map((s, i) => ({
        key: s.label || `series-${i}`,
        label: s.label,
        data: s.points.map((p) => p.y),
    }))

    return (
        <div>
            <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '400px' }}>
                <TimeSeriesBarChart
                    series={chartSeries}
                    labels={labels}
                    theme={THEME}
                    config={{
                        xAxis: { tickFormatter: (value) => formatDate(value) },
                        yAxis: {
                            ...(yAxisLabel ? { label: yAxisLabel } : {}),
                            format: yAxisFormat,
                            showGrid: true,
                        },
                    }}
                />
            </div>

            {showLegend && series.length > 1 && (
                <div
                    style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: '1rem',
                        justifyContent: 'center',
                        marginTop: '0.5rem',
                        fontSize: '0.75rem',
                    }}
                >
                    {series.map((s, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                            <div
                                style={{
                                    width: '12px',
                                    height: '12px',
                                    borderRadius: '2px',
                                    backgroundColor: CHART_COLORS[i % CHART_COLORS.length],
                                }}
                            />
                            <span style={{ color: 'var(--color-text-secondary, #6b7280)' }}>{s.label}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
