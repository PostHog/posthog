import type { ReactElement } from 'react'

import { formatDate, formatNumber } from '../utils'

// TODO(quill): replace with a Quill chart primitive (e.g. `LineChart` /
// `Charts.Line`) once Quill ships one. Quill currently has no chart layer —
// it stops at primitives/components/blocks, none of which render data viz.
// This bespoke SVG renderer uses Quill design tokens via the host bridge so
// the visual language already matches.

const CHART_HEIGHT = 200
const CHART_WIDTH = 400
const PADDING = { top: 20, right: 20, bottom: 40, left: 50 }

const COLORS = [
    'var(--posthog-chart-1, #1d4aff)',
    'var(--posthog-chart-2, #621da6)',
    'var(--posthog-chart-3, #42827e)',
    'var(--posthog-chart-4, #ce0e74)',
    'var(--posthog-chart-5, #f14f58)',
    'var(--posthog-chart-6, #7c440e)',
    'var(--posthog-chart-7, #529a0a)',
    'var(--posthog-chart-8, #0476fb)',
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

export interface LineChartProps {
    series: Series[]
    labels: string[]
    maxValue: number
    showLegend?: boolean
    yAxisLabel?: string | undefined
}

export function LineChart({ series, labels, maxValue, showLegend = true, yAxisLabel }: LineChartProps): ReactElement {
    const innerWidth = CHART_WIDTH - PADDING.left - PADDING.right
    const innerHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom

    const xScale = (index: number): number => PADDING.left + (index / Math.max(labels.length - 1, 1)) * innerWidth
    const yScale = (value: number): number => PADDING.top + innerHeight - (value / maxValue) * innerHeight

    return (
        <div>
            <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} style={{ width: '100%', height: '400px' }}>
                {yAxisLabel && (
                    <text
                        x={12}
                        y={PADDING.top + innerHeight / 2}
                        textAnchor="middle"
                        fontSize="11"
                        fill="var(--color-text-secondary, #6b7280)"
                        transform={`rotate(-90, 12, ${PADDING.top + innerHeight / 2})`}
                    >
                        {yAxisLabel}
                    </text>
                )}

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
                    if (labels.length > 7 && i % Math.ceil(labels.length / 7) !== 0) {
                        return null
                    }

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
                    if (s.points.length === 0) {
                        return null
                    }

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
