import { type ReactElement, useMemo } from 'react'

import { type ChartTheme, type Series as QuillSeries, TimeSeriesLineChart } from '@posthog/quill-charts'

import { formatDate, formatNumber } from '../utils'

// Quill chart colors. Canvas can't read `var(--…)`, so we resolve the host CSS
// variables to concrete strings and fall back to the same hexes base.css ships.
const CHART_VARS = [
    ['--posthog-chart-1', '#1d4aff'],
    ['--posthog-chart-2', '#621da6'],
    ['--posthog-chart-3', '#42827e'],
    ['--posthog-chart-4', '#ce0e74'],
    ['--posthog-chart-5', '#f14f58'],
    ['--posthog-chart-6', '#7c440e'],
    ['--posthog-chart-7', '#529a0a'],
    ['--posthog-chart-8', '#0476fb'],
] as const

function resolveVar(name: string, fallback: string): string {
    if (typeof window === 'undefined') {
        return fallback
    }
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return value || fallback
}

export interface DataPoint {
    x: number
    y: number
    label: string
}

export interface Series {
    label: string
    points: DataPoint[]
}

export interface LineChartProps {
    series: Series[]
    labels: string[]
    maxValue: number
    showLegend?: boolean
    yAxisLabel?: string | undefined
}

export function LineChart({ series, labels, showLegend = true, yAxisLabel }: LineChartProps): ReactElement {
    const palette = useMemo(() => CHART_VARS.map(([name, fallback]) => resolveVar(name, fallback)), [])

    const theme: ChartTheme = useMemo(
        () => ({
            colors: palette,
            backgroundColor: resolveVar('--color-background-primary', '#fff'),
            axisColor: resolveVar('--color-text-secondary', '#6b7280'),
            gridColor: resolveVar('--color-border-primary', '#e5e7eb'),
            tooltipBackground: resolveVar('--color-background-secondary', '#f9fafb'),
            tooltipColor: resolveVar('--color-text-primary', '#101828'),
        }),
        [palette]
    )

    const quillSeries: QuillSeries[] = useMemo(
        () =>
            series.map((s, i) => ({
                key: s.label || `series-${i}`,
                label: s.label,
                data: s.points.map((p) => p.y),
                color: palette[i % palette.length],
            })),
        [series, palette]
    )

    return (
        <div>
            <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '400px' }}>
                <TimeSeriesLineChart
                    series={quillSeries}
                    labels={labels}
                    theme={theme}
                    config={{
                        xAxis: { tickFormatter: (value) => formatDate(value) },
                        yAxis: { label: yAxisLabel, showGrid: true, tickFormatter: (value) => formatNumber(value) },
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
                                    backgroundColor: palette[i % palette.length],
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
