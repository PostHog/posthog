import { useMemo, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

import { DemoChartColor, DemoChartData } from '../types'

const CHART_COLOR: Record<DemoChartColor, string> = {
    accent: 'var(--data-color-1)',
    muted: 'var(--color-text-tertiary)',
    success: 'var(--success)',
    danger: 'var(--danger)',
}

const PLOT_TOP = 10
const PLOT_BOTTOM = 8

export interface AnnotatedLineChartProps {
    data: DemoChartData
    /** Plot height in view-box units */
    height?: number
    /** View-box width; match it to the rendered width so text keeps its size */
    viewWidth?: number
    /** Pulsing dot on the newest point of the first series */
    live?: boolean
    className?: string
}

function formatValue(value: number): string {
    return Math.abs(value) >= 100 || Number.isInteger(value) ? Math.round(value).toLocaleString() : value.toFixed(1)
}

/**
 * Inline line chart with vertical event annotations, hover tooltips, and an
 * optional live pulse. Data is mock numeric series, so this stays an SVG
 * primitive rather than going through the insights charting stack.
 */
export function AnnotatedLineChart({
    data,
    height = 150,
    viewWidth = 300,
    live,
    className,
}: AnnotatedLineChartProps): JSX.Element {
    const [hoverIndex, setHoverIndex] = useState<number | null>(null)

    const pointCount = data.series[0]?.points.length ?? 0

    const { toX, toY } = useMemo(() => {
        const values = data.series.flatMap((series) => series.points)
        if (data.baselineValue !== undefined) {
            values.push(data.baselineValue)
        }
        const min = Math.min(...values, 0)
        const max = Math.max(...values, 1)
        const span = max - min || 1
        const plotHeight = height - PLOT_TOP - PLOT_BOTTOM
        return {
            toX: (index: number): number => (pointCount > 1 ? (index / (pointCount - 1)) * viewWidth : 0),
            toY: (value: number): number => PLOT_TOP + plotHeight - ((value - min) / span) * plotHeight,
        }
    }, [data, height, viewWidth, pointCount])

    const onMouseMove = (event: React.MouseEvent<SVGSVGElement>): void => {
        if (pointCount < 2) {
            return
        }
        const rect = event.currentTarget.getBoundingClientRect()
        const fraction = (event.clientX - rect.left) / rect.width
        setHoverIndex(Math.max(0, Math.min(pointCount - 1, Math.round(fraction * (pointCount - 1)))))
    }

    const lastIndex = pointCount - 1
    const primarySeries = data.series[0]

    return (
        <div className={cn('relative', className)}>
            <svg
                viewBox={`0 0 ${viewWidth} ${height}`}
                className="block h-auto w-full cursor-crosshair"
                role="img"
                aria-label={data.series.map((series) => series.name).join(' vs ')}
                onMouseMove={onMouseMove}
                onMouseLeave={() => setHoverIndex(null)}
            >
                {data.baselineValue !== undefined ? (
                    <>
                        <line
                            x1={0}
                            y1={toY(data.baselineValue)}
                            x2={viewWidth}
                            y2={toY(data.baselineValue)}
                            stroke="var(--color-border-primary)"
                            strokeWidth={1}
                            strokeDasharray="3 3"
                        />
                        {data.baselineLabel ? (
                            <text
                                x={0}
                                y={toY(data.baselineValue) - 4}
                                fontSize={9}
                                className="font-mono"
                                fill="var(--color-text-tertiary)"
                            >
                                {data.baselineLabel}
                            </text>
                        ) : null}
                    </>
                ) : null}
                {data.annotations?.map((annotation) => (
                    <g key={`${annotation.index}-${annotation.label}`}>
                        <line
                            x1={toX(annotation.index)}
                            y1={8}
                            x2={toX(annotation.index)}
                            y2={height - 4}
                            stroke={CHART_COLOR[annotation.color]}
                            strokeWidth={1.2}
                            strokeDasharray="4 3"
                        />
                        <text
                            x={annotation.labelAnchor === 'end' ? toX(annotation.index) - 6 : toX(annotation.index) + 6}
                            y={16}
                            fontSize={9.5}
                            textAnchor={annotation.labelAnchor === 'end' ? 'end' : 'start'}
                            fill={CHART_COLOR[annotation.color]}
                        >
                            {annotation.label}
                        </text>
                    </g>
                ))}
                {data.series.map((series) => (
                    <polyline
                        key={series.name}
                        points={series.points.map((value, index) => `${toX(index)},${toY(value)}`).join(' ')}
                        fill="none"
                        stroke={CHART_COLOR[series.color]}
                        strokeWidth={series.strokeWidth ?? 1.8}
                        strokeDasharray={series.dashed ? '4 3' : undefined}
                    />
                ))}
                {live && primarySeries && lastIndex >= 0 ? (
                    <circle
                        cx={toX(lastIndex)}
                        cy={toY(primarySeries.points[lastIndex])}
                        r={3}
                        fill={CHART_COLOR[primarySeries.color]}
                        className="animate-pulse motion-reduce:animate-none"
                    />
                ) : null}
                {hoverIndex !== null ? (
                    <g>
                        <line
                            x1={toX(hoverIndex)}
                            y1={PLOT_TOP - 4}
                            x2={toX(hoverIndex)}
                            y2={height - 4}
                            stroke="var(--color-text-tertiary)"
                            strokeWidth={1}
                        />
                        {data.series.map((series) => (
                            <circle
                                key={series.name}
                                cx={toX(hoverIndex)}
                                cy={toY(series.points[hoverIndex])}
                                r={2.6}
                                fill={CHART_COLOR[series.color]}
                                stroke="var(--color-bg-surface-primary)"
                                strokeWidth={1}
                            />
                        ))}
                    </g>
                ) : null}
            </svg>
            {hoverIndex !== null && (
                <div
                    className="pointer-events-none absolute top-1 z-10 flex flex-col gap-0.5 rounded bg-surface-tooltip px-2 py-1.5 text-xs whitespace-nowrap text-primary-inverse shadow-md"
                    style={{
                        left: `${lastIndex > 0 ? (hoverIndex / lastIndex) * 100 : 0}%`,
                        transform: hoverIndex > lastIndex / 2 ? 'translateX(calc(-100% - 8px))' : 'translateX(8px)',
                    }}
                >
                    <span className="font-semibold">{data.pointLabels[hoverIndex] ?? ''}</span>
                    {data.series.map((series) => (
                        <span key={series.name} className="flex items-center gap-1.5">
                            <span
                                className="size-2 rounded-full"
                                // Series colors are data-driven tokens, so they can't be static Tailwind classes
                                style={{ backgroundColor: CHART_COLOR[series.color] }}
                            />
                            <span className="text-secondary-inverse">{series.name}</span>
                            <span className="ml-auto pl-2 font-mono">
                                {formatValue(series.points[hoverIndex])}
                                {data.unit ? ` ${data.unit}` : ''}
                            </span>
                        </span>
                    ))}
                </div>
            )}
            {data.xLabels.length ? (
                <div className="flex justify-between font-mono text-[10px] text-tertiary">
                    {data.xLabels.map((label) => (
                        <span key={label}>{label}</span>
                    ))}
                </div>
            ) : null}
        </div>
    )
}
