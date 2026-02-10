import type { ReactElement } from 'react'

import { formatDate, formatNumber } from '../utils'

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
}

export function BarChart({ series, labels, maxValue, showLegend = true }: BarChartProps): ReactElement {
    const innerWidth = CHART_WIDTH - PADDING.left - PADDING.right
    const innerHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom

    const numBars = labels.length
    const numSeries = series.length
    const barGroupWidth = innerWidth / numBars
    const barWidth = Math.min(barGroupWidth * 0.8, 40) / numSeries
    const barGap = barWidth * 0.1

    return (
        <div>
            <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} style={{ width: '100%', height: '400px' }}>
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
                    if (labels.length > 7 && i % Math.ceil(labels.length / 7) !== 0) {
                        return null
                    }
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
                                    backgroundColor: COLORS[i % COLORS.length],
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
