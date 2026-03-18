import type { ReactElement } from 'react'

import { formatNumber } from '../utils'

const BAR_HEIGHT = 32
const BAR_GAP = 8
const LABEL_WIDTH = 120
const VALUE_WIDTH = 80

export interface HorizontalBar {
    label: string
    value: number
    /** Optional secondary text shown inside the bar */
    innerText?: string
}

export interface HorizontalBarChartProps {
    bars: HorizontalBar[]
    /** If provided, bars are sized relative to this. Otherwise uses max value. */
    maxValue?: number
    /** Color for the bars. Can be a function for per-bar colors. */
    color?: string | ((index: number, bar: HorizontalBar) => string)
}

const DEFAULT_COLOR = 'var(--posthog-chart-1, #1d4ed8)'

export function HorizontalBarChart({ bars, maxValue, color = DEFAULT_COLOR }: HorizontalBarChartProps): ReactElement {
    if (bars.length === 0) {
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

    const max = maxValue ?? Math.max(...bars.map((b) => b.value), 1)

    const getColor = (index: number, bar: HorizontalBar): string => {
        if (typeof color === 'function') {
            return color(index, bar)
        }
        return color
    }

    return (
        <div style={{ padding: '0.5rem 0' }}>
            {bars.map((bar, index) => {
                const widthPercent = (bar.value / max) * 100
                const barColor = getColor(index, bar)

                return (
                    <div
                        key={index}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.75rem',
                            marginBottom: index < bars.length - 1 ? `${BAR_GAP}px` : 0,
                        }}
                    >
                        {/* Label */}
                        <div
                            style={{
                                width: `${LABEL_WIDTH}px`,
                                fontSize: '0.875rem',
                                color: 'var(--color-text-primary, #101828)',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                flexShrink: 0,
                            }}
                            title={bar.label}
                        >
                            {bar.label}
                        </div>

                        {/* Bar container */}
                        <div
                            style={{
                                flex: 1,
                                height: `${BAR_HEIGHT}px`,
                                backgroundColor: 'var(--color-background-secondary, #f9fafb)',
                                borderRadius: '4px',
                                overflow: 'hidden',
                                position: 'relative',
                            }}
                        >
                            {/* Filled bar */}
                            <div
                                style={{
                                    height: '100%',
                                    width: `${widthPercent}%`,
                                    backgroundColor: barColor,
                                    borderRadius: '4px',
                                    transition: 'width 0.3s ease',
                                }}
                            />

                            {/* Inner text */}
                            {bar.innerText && (
                                <div
                                    style={{
                                        position: 'absolute',
                                        left: '8px',
                                        top: '50%',
                                        transform: 'translateY(-50%)',
                                        fontSize: '0.75rem',
                                        fontWeight: 500,
                                        color:
                                            widthPercent > 30
                                                ? 'var(--color-text-inverse, #fff)'
                                                : 'var(--color-text-secondary, #6b7280)',
                                    }}
                                >
                                    {bar.innerText}
                                </div>
                            )}
                        </div>

                        {/* Value */}
                        <div
                            style={{
                                width: `${VALUE_WIDTH}px`,
                                textAlign: 'right',
                                fontSize: '0.875rem',
                                fontWeight: 500,
                                color: 'var(--color-text-primary, #101828)',
                                flexShrink: 0,
                            }}
                        >
                            {formatNumber(bar.value)}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
