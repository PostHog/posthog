import type { ReactElement } from 'react'
import type { TrendsVisualizerProps, TrendsResultItem } from './types'
import { getDisplayType, isBarChart, formatNumber, formatDate, getSeriesLabel } from './utils'

const CHART_HEIGHT = 200
const CHART_WIDTH = 400
const PADDING = { top: 20, right: 20, bottom: 40, left: 50 }

const COLORS = [
    'var(--posthog-chart-1, #1d4ed8)',
    'var(--posthog-chart-2, #7c3aed)',
    'var(--posthog-chart-3, #059669)',
    'var(--posthog-chart-4, #dc2626)',
    'var(--posthog-chart-5, #ea580c)',
]

interface DataPoint {
    x: number
    y: number
    label: string
    value: number
}

function prepareChartData(results: TrendsResultItem[]): {
    series: Array<{ label: string; points: DataPoint[] }>
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
                value,
            }
        })
        return {
            label: getSeriesLabel(item, seriesIndex),
            points,
        }
    })

    return { series, labels, maxValue: maxValue || 1 }
}

function LineChart({
    series,
    labels,
    maxValue,
}: {
    series: Array<{ label: string; points: DataPoint[] }>
    labels: string[]
    maxValue: number
}): ReactElement {
    const innerWidth = CHART_WIDTH - PADDING.left - PADDING.right
    const innerHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom

    const xScale = (index: number): number => PADDING.left + (index / Math.max(labels.length - 1, 1)) * innerWidth

    const yScale = (value: number): number => PADDING.top + innerHeight - (value / maxValue) * innerHeight

    return (
        <svg
            width="100%"
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            style={{ maxWidth: '100%', height: 'auto' }}
        >
            {/* Y-axis labels */}
            {[0, 0.5, 1].map((ratio) => {
                const value = maxValue * ratio
                const y = yScale(value)
                return (
                    <g key={ratio}>
                        <line
                            x1={PADDING.left}
                            y1={y}
                            x2={CHART_WIDTH - PADDING.right}
                            y2={y}
                            stroke="var(--color-border-primary, #e5e7eb)"
                            strokeDasharray={ratio === 0 ? '0' : '4,4'}
                        />
                        <text
                            x={PADDING.left - 8}
                            y={y + 4}
                            textAnchor="end"
                            fontSize="10"
                            fill="var(--color-text-secondary, #6b7280)"
                        >
                            {formatNumber(value)}
                        </text>
                    </g>
                )
            })}

            {/* X-axis labels */}
            {labels.map((label, i) => {
                if (labels.length > 7 && i % Math.ceil(labels.length / 7) !== 0) return null
                return (
                    <text
                        key={i}
                        x={xScale(i)}
                        y={CHART_HEIGHT - 8}
                        textAnchor="middle"
                        fontSize="10"
                        fill="var(--color-text-secondary, #6b7280)"
                    >
                        {formatDate(label)}
                    </text>
                )
            })}

            {/* Lines */}
            {series.map((s, seriesIndex) => {
                if (s.points.length === 0) return null

                const pathD = s.points
                    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(p.x)} ${yScale(p.y)}`)
                    .join(' ')

                return (
                    <g key={seriesIndex}>
                        <path d={pathD} fill="none" stroke={COLORS[seriesIndex % COLORS.length]} strokeWidth="2" />
                        {s.points.map((p, i) => (
                            <circle
                                key={i}
                                cx={xScale(p.x)}
                                cy={yScale(p.y)}
                                r="3"
                                fill={COLORS[seriesIndex % COLORS.length]}
                            />
                        ))}
                    </g>
                )
            })}
        </svg>
    )
}

function BarChart({
    series,
    labels,
    maxValue,
}: {
    series: Array<{ label: string; points: DataPoint[] }>
    labels: string[]
    maxValue: number
}): ReactElement {
    const innerWidth = CHART_WIDTH - PADDING.left - PADDING.right
    const innerHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom

    const numBars = labels.length
    const numSeries = series.length
    const barGroupWidth = innerWidth / numBars
    const barWidth = Math.min(barGroupWidth * 0.8, 40) / numSeries
    const barGap = barWidth * 0.1

    return (
        <svg
            width="100%"
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            style={{ maxWidth: '100%', height: 'auto' }}
        >
            {/* Y-axis labels */}
            {[0, 0.5, 1].map((ratio) => {
                const value = maxValue * ratio
                const y = PADDING.top + innerHeight - (value / maxValue) * innerHeight
                return (
                    <g key={ratio}>
                        <line
                            x1={PADDING.left}
                            y1={y}
                            x2={CHART_WIDTH - PADDING.right}
                            y2={y}
                            stroke="var(--color-border-primary, #e5e7eb)"
                            strokeDasharray={ratio === 0 ? '0' : '4,4'}
                        />
                        <text
                            x={PADDING.left - 8}
                            y={y + 4}
                            textAnchor="end"
                            fontSize="10"
                            fill="var(--color-text-secondary, #6b7280)"
                        >
                            {formatNumber(value)}
                        </text>
                    </g>
                )
            })}

            {/* X-axis labels */}
            {labels.map((label, i) => {
                if (labels.length > 7 && i % Math.ceil(labels.length / 7) !== 0) return null
                const x = PADDING.left + (i + 0.5) * barGroupWidth
                return (
                    <text
                        key={i}
                        x={x}
                        y={CHART_HEIGHT - 8}
                        textAnchor="middle"
                        fontSize="10"
                        fill="var(--color-text-secondary, #6b7280)"
                    >
                        {formatDate(label)}
                    </text>
                )
            })}

            {/* Bars */}
            {series.map((s, seriesIndex) =>
                s.points.map((p, i) => {
                    const barHeight = (p.y / maxValue) * innerHeight
                    const groupX = PADDING.left + i * barGroupWidth
                    const barX = groupX + (barGroupWidth - numSeries * barWidth - (numSeries - 1) * barGap) / 2
                    const x = barX + seriesIndex * (barWidth + barGap)
                    const y = PADDING.top + innerHeight - barHeight

                    return (
                        <rect
                            key={`${seriesIndex}-${i}`}
                            x={x}
                            y={y}
                            width={barWidth}
                            height={barHeight}
                            fill={COLORS[seriesIndex % COLORS.length]}
                            rx="2"
                        />
                    )
                })
            )}
        </svg>
    )
}

function BoldNumber({ results }: { results: TrendsResultItem[] }): ReactElement {
    const total = results.reduce((sum, item) => {
        if (typeof item.count === 'number') {
            return sum + item.count
        }
        if (item.data && item.data.length > 0) {
            return sum + item.data.reduce((a, b) => a + b, 0)
        }
        return sum
    }, 0)

    const label = results[0] ? getSeriesLabel(results[0], 0) : 'Total'

    return (
        <div style={{ textAlign: 'center', padding: '2rem' }}>
            <div
                style={{
                    fontSize: '3rem',
                    fontWeight: 'bold',
                    color: 'var(--color-text-primary, #101828)',
                }}
            >
                {formatNumber(total)}
            </div>
            <div
                style={{
                    fontSize: '0.875rem',
                    color: 'var(--color-text-secondary, #6b7280)',
                    marginTop: '0.5rem',
                }}
            >
                {label}
            </div>
        </div>
    )
}

function Legend({ series }: { series: Array<{ label: string }> }): ReactElement | null {
    if (series.length <= 1) return null

    return (
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
                            backgroundColor: COLORS[i % COLORS.length],
                        }}
                    />
                    <span style={{ color: 'var(--color-text-secondary, #6b7280)' }}>{s.label}</span>
                </div>
            ))}
        </div>
    )
}

export function TrendsVisualizer({ query, results }: TrendsVisualizerProps): ReactElement {
    const displayType = getDisplayType(query)
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
        return <BoldNumber results={results} />
    }

    const ChartComponent = isBarChart(displayType) ? BarChart : LineChart

    return (
        <div>
            <ChartComponent series={series} labels={labels} maxValue={maxValue} />
            <Legend series={series} />
        </div>
    )
}
