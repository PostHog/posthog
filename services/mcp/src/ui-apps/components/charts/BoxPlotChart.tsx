import type { ReactElement } from 'react'

import type { BoxPlotDatum } from '../types'
import { formatDate, formatNumber } from '../utils'

const CHART_HEIGHT = 260
const CHART_WIDTH = 400
const PADDING = { top: 20, right: 20, bottom: 50, left: 50 }

const COLORS = [
    'var(--posthog-chart-1, #1d4ed8)',
    'var(--posthog-chart-2, #7c3aed)',
    'var(--posthog-chart-3, #059669)',
    'var(--posthog-chart-4, #dc2626)',
    'var(--posthog-chart-5, #ea580c)',
]

export interface BoxPlotSeries {
    label: string
    seriesIndex: number
    data: BoxPlotDatum[]
}

export interface BoxPlotChartProps {
    series: BoxPlotSeries[]
    labels: string[]
    maxValue: number
    minValue: number
    showLegend?: boolean
    yAxisLabel?: string | undefined
}

export function BoxPlotChart({
    series,
    labels,
    maxValue,
    minValue,
    showLegend = true,
    yAxisLabel,
}: BoxPlotChartProps): ReactElement {
    const innerWidth = CHART_WIDTH - PADDING.left - PADDING.right
    const innerHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom

    const valueRange = Math.max(maxValue - minValue, 1)
    const numGroups = Math.max(labels.length, 1)
    const numSeries = Math.max(series.length, 1)
    const groupWidth = innerWidth / numGroups
    const boxSlot = Math.min(groupWidth * 0.8, 60) / numSeries
    const boxWidth = boxSlot * 0.8
    const boxGap = boxSlot - boxWidth

    const yScale = (value: number): number =>
        PADDING.top + innerHeight - ((value - minValue) / valueRange) * innerHeight

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

                {[0, 0.5, 1].map((ratio) => {
                    const value = minValue + valueRange * ratio
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

                {labels.map((label, i) => {
                    if (labels.length > 7 && i % Math.ceil(labels.length / 7) !== 0) {
                        return null
                    }
                    const x = PADDING.left + (i + 0.5) * groupWidth
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

                {series.map((s, seriesIndex) => {
                    const color = COLORS[seriesIndex % COLORS.length]
                    return s.data.map((d, i) => {
                        const groupX = PADDING.left + i * groupWidth
                        const slotX =
                            groupX + (groupWidth - numSeries * boxSlot) / 2 + seriesIndex * boxSlot + boxGap / 2
                        const centerX = slotX + boxWidth / 2

                        const yMin = yScale(d.min)
                        const yMax = yScale(d.max)
                        const yP25 = yScale(d.p25)
                        const yP75 = yScale(d.p75)
                        const yMedian = yScale(d.median)
                        const yMean = yScale(d.mean)

                        return (
                            <g key={`${seriesIndex}-${i}`}>
                                {/* whisker line */}
                                <line x1={centerX} y1={yMin} x2={centerX} y2={yMax} stroke={color} strokeWidth="1" />
                                {/* min cap */}
                                <line
                                    x1={centerX - boxWidth / 4}
                                    y1={yMin}
                                    x2={centerX + boxWidth / 4}
                                    y2={yMin}
                                    stroke={color}
                                    strokeWidth="1"
                                />
                                {/* max cap */}
                                <line
                                    x1={centerX - boxWidth / 4}
                                    y1={yMax}
                                    x2={centerX + boxWidth / 4}
                                    y2={yMax}
                                    stroke={color}
                                    strokeWidth="1"
                                />
                                {/* IQR box */}
                                <rect
                                    x={slotX}
                                    y={yP75}
                                    width={boxWidth}
                                    height={Math.max(yP25 - yP75, 1)}
                                    fill={color}
                                    fillOpacity="0.25"
                                    stroke={color}
                                    strokeWidth="1"
                                />
                                {/* median */}
                                <line
                                    x1={slotX}
                                    y1={yMedian}
                                    x2={slotX + boxWidth}
                                    y2={yMedian}
                                    stroke={color}
                                    strokeWidth="2"
                                />
                                {/* mean marker */}
                                <circle cx={centerX} cy={yMean} r={2} fill={color} />
                                <title>
                                    {`${d.label}\nmin: ${formatNumber(d.min)}\np25: ${formatNumber(d.p25)}\nmedian: ${formatNumber(d.median)}\nmean: ${formatNumber(d.mean)}\np75: ${formatNumber(d.p75)}\nmax: ${formatNumber(d.max)}`}
                                </title>
                            </g>
                        )
                    })
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
