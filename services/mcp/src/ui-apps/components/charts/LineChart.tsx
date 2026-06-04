import { type ReactElement } from 'react'

import { type Series as ChartSeries, type YAxisFormat, TimeSeriesLineChart } from '@posthog/quill-charts'

import { formatDate } from '../utils'
import { CHART_COLORS, CHART_THEME } from './theme'
import type { Series } from './types'

export interface LineChartProps {
    series: Series[]
    labels: string[]
    showLegend?: boolean
    yAxisLabel?: string | undefined
    /** Y-axis value format. Mirrors a trends insight's `aggregationAxisFormat`; defaults to `numeric`. */
    yAxisFormat?: YAxisFormat | undefined
}

export function LineChart({
    series,
    labels,
    showLegend = true,
    yAxisLabel,
    yAxisFormat = 'numeric',
}: LineChartProps): ReactElement {
    // Color omitted so the chart assigns one per series from THEME.colors by index.
    const chartSeries: ChartSeries[] = series.map((s, i) => ({
        key: s.label || `series-${i}`,
        label: s.label,
        data: s.points.map((p) => p.y),
    }))

    return (
        <div>
            <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '400px' }}>
                <TimeSeriesLineChart
                    series={chartSeries}
                    labels={labels}
                    theme={CHART_THEME}
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
