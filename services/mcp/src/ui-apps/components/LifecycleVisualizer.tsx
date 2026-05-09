import { type ReactElement } from 'react'

import { EmptyState } from '@posthog/mosaic'

import type { LifecycleResultItem, LifecycleStatus, LifecycleVisualizerProps } from './types'
import { formatDate, formatNumber } from './utils'

const CHART_HEIGHT = 320
const CHART_WIDTH = 600
const PADDING = { top: 24, right: 24, bottom: 48, left: 56 }

// Conventional lifecycle bucket colors — mirrors --color-lifecycle-* in frontend/src/styles/base.scss.
const LIFECYCLE_COLORS: Record<LifecycleStatus, string> = {
    new: '#1d4aff',
    returning: '#388600',
    resurrecting: '#a56eff',
    dormant: '#db3707',
}

// Stack order — positive buckets stack upward, dormant goes below zero.
const POSITIVE_STATUSES: LifecycleStatus[] = ['new', 'returning', 'resurrecting']
const NEGATIVE_STATUSES: LifecycleStatus[] = ['dormant']
const ALL_STATUSES: LifecycleStatus[] = [...POSITIVE_STATUSES, ...NEGATIVE_STATUSES]

interface SeriesByStatus {
    status: LifecycleStatus
    label: string
    data: number[]
}

function groupByStatus(results: LifecycleResultItem[]): {
    byStatus: Map<LifecycleStatus, SeriesByStatus>
    labels: string[]
} {
    const labels = results[0]?.days || results[0]?.labels || []
    const byStatus = new Map<LifecycleStatus, SeriesByStatus>()

    for (const item of results) {
        if (!item.status || !ALL_STATUSES.includes(item.status)) {
            continue
        }
        // Multiple series can share the same status (e.g. when grouping by event).
        // Sum element-wise.
        const existing = byStatus.get(item.status)
        const data = item.data ?? []
        if (existing) {
            for (let i = 0; i < data.length; i++) {
                existing.data[i] = (existing.data[i] ?? 0) + (data[i] ?? 0)
            }
        } else {
            byStatus.set(item.status, {
                status: item.status,
                label: item.status,
                data: [...data],
            })
        }
    }

    return { byStatus, labels }
}

function computeBounds(
    byStatus: Map<LifecycleStatus, SeriesByStatus>,
    dataLength: number,
    isVisible: (status: LifecycleStatus) => boolean
): { max: number; min: number } {
    let max = 0
    let min = 0
    for (let i = 0; i < dataLength; i++) {
        let positiveStack = 0
        let negativeStack = 0
        for (const status of POSITIVE_STATUSES) {
            if (!isVisible(status)) {
                continue
            }
            const value = byStatus.get(status)?.data[i] ?? 0
            if (value > 0) {
                positiveStack += value
            }
        }
        for (const status of NEGATIVE_STATUSES) {
            if (!isVisible(status)) {
                continue
            }
            const value = byStatus.get(status)?.data[i] ?? 0
            if (value < 0) {
                negativeStack += value
            }
        }
        if (positiveStack > max) {
            max = positiveStack
        }
        if (negativeStack < min) {
            min = negativeStack
        }
    }
    return { max, min }
}

export function LifecycleVisualizer({ query, results }: LifecycleVisualizerProps): ReactElement {
    if (!results || results.length === 0) {
        return <EmptyState icon="chart" description="No data available" />
    }

    const { byStatus, labels } = groupByStatus(results)
    const dataLength = labels.length
    if (dataLength === 0 || byStatus.size === 0) {
        return <EmptyState icon="chart" description="No data available" />
    }

    // `toggledLifecycles` is a client-side filter in the main app: the backend always returns
    // all four buckets and the UI hides the toggled-off ones. Mirror that here.
    const toggledLifecycles = query?.lifecycleFilter?.toggledLifecycles
    const isVisible = (status: LifecycleStatus): boolean =>
        byStatus.has(status) && (!toggledLifecycles || toggledLifecycles.includes(status))
    const visibleBuckets = ALL_STATUSES.filter(isVisible)
    const showLegend = query?.lifecycleFilter?.showLegend ?? true

    const { max, min } = computeBounds(byStatus, dataLength, isVisible)
    const range = Math.max(max - min, 1)

    const innerWidth = CHART_WIDTH - PADDING.left - PADDING.right
    const innerHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom
    const zeroY = PADDING.top + (max / range) * innerHeight
    const valueToY = (value: number): number => zeroY - (value / range) * innerHeight
    const barGroupWidth = innerWidth / dataLength
    const barWidth = Math.min(barGroupWidth * 0.7, 36)

    // Tick values: 0 plus a few evenly-spaced positions above and below.
    const positiveTicks = [0.25, 0.5, 0.75, 1].map((ratio) => max * ratio).filter((v) => v > 0)
    const negativeTicks = [0.25, 0.5, 0.75, 1].map((ratio) => min * ratio).filter((v) => v < 0)
    const ticks = [...negativeTicks.reverse(), 0, ...positiveTicks]

    return (
        <div>
            <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} style={{ width: '100%' }}>
                {/* Y-axis grid + labels */}
                {ticks.map((value) => {
                    const y = valueToY(value)
                    return (
                        <g key={value}>
                            <line
                                x1={PADDING.left}
                                y1={y}
                                x2={CHART_WIDTH - PADDING.right}
                                y2={y}
                                stroke="var(--color-border-primary, #e5e7eb)"
                                strokeDasharray={value === 0 ? '0' : '4,4'}
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

                {/* X-axis labels — thin out when crowded. */}
                {labels.map((label, i) => {
                    if (labels.length > 8 && i % Math.ceil(labels.length / 8) !== 0) {
                        return null
                    }
                    const x = PADDING.left + (i + 0.5) * barGroupWidth
                    return (
                        <text
                            key={i}
                            x={x}
                            y={CHART_HEIGHT - 16}
                            textAnchor="middle"
                            fontSize="10"
                            fill="var(--color-text-secondary, #6b7280)"
                        >
                            {formatDate(label)}
                        </text>
                    )
                })}

                {/* Stacked bars — positive buckets stack upward, dormant extends downward. */}
                {Array.from({ length: dataLength }).map((_, i) => {
                    const groupX = PADDING.left + i * barGroupWidth
                    const x = groupX + (barGroupWidth - barWidth) / 2

                    let positiveCursor = 0
                    let negativeCursor = 0
                    return (
                        <g key={i}>
                            {POSITIVE_STATUSES.map((status) => {
                                if (!isVisible(status)) {
                                    return null
                                }
                                const series = byStatus.get(status)
                                const value = series?.data[i] ?? 0
                                if (value <= 0) {
                                    return null
                                }
                                const yTop = valueToY(positiveCursor + value)
                                const yBottom = valueToY(positiveCursor)
                                positiveCursor += value
                                return (
                                    <rect
                                        key={`${status}-${i}`}
                                        x={x}
                                        y={yTop}
                                        width={barWidth}
                                        height={Math.max(yBottom - yTop, 0)}
                                        fill={LIFECYCLE_COLORS[status]}
                                    />
                                )
                            })}
                            {NEGATIVE_STATUSES.map((status) => {
                                if (!isVisible(status)) {
                                    return null
                                }
                                const series = byStatus.get(status)
                                const value = series?.data[i] ?? 0
                                if (value >= 0) {
                                    return null
                                }
                                const yTop = valueToY(negativeCursor)
                                const yBottom = valueToY(negativeCursor + value)
                                negativeCursor += value
                                return (
                                    <rect
                                        key={`${status}-${i}`}
                                        x={x}
                                        y={yTop}
                                        width={barWidth}
                                        height={Math.max(yBottom - yTop, 0)}
                                        fill={LIFECYCLE_COLORS[status]}
                                    />
                                )
                            })}
                        </g>
                    )
                })}
            </svg>

            {showLegend && visibleBuckets.length > 0 && (
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
                    {visibleBuckets.map((status) => (
                        <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                            <div
                                style={{
                                    width: '12px',
                                    height: '12px',
                                    borderRadius: '2px',
                                    backgroundColor: LIFECYCLE_COLORS[status],
                                }}
                            />
                            <span style={{ color: 'var(--color-text-secondary, #6b7280)' }}>{status}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
