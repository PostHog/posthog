export type DemoChartColor = 'accent' | 'muted' | 'success' | 'danger'

const CHART_COLOR: Record<DemoChartColor, string> = {
    accent: 'var(--data-color-1)',
    muted: 'var(--color-text-tertiary)',
    success: 'var(--success)',
    danger: 'var(--danger)',
}

export interface DemoChartSeries {
    /** Raw SVG polyline points in view-box coordinates, e.g. "0,111 30,110 …" */
    points: string
    color: DemoChartColor
    dashed?: boolean
    strokeWidth?: number
}

export interface DemoChartAnnotation {
    /** X position in view-box coordinates */
    x: number
    label: string
    color: DemoChartColor
    /** Anchor the label to the left of the line instead of the right */
    labelAnchor?: 'start' | 'end'
}

export interface AnnotatedLineChartProps {
    viewWidth: number
    viewHeight: number
    series: DemoChartSeries[]
    /** Vertical event markers (deploys, ramp steps, detection) */
    annotations?: DemoChartAnnotation[]
    /** Y position of a horizontal dashed baseline, in view-box coordinates */
    baselineY?: number
    baselineLabel?: string
    /** Labels spread evenly along the x axis, below the plot */
    xLabels?: string[]
    className?: string
}

/**
 * Small inline line chart with vertical event annotations, for the demo report
 * and monitor pages. Point data is pre-baked mock geometry, not real series, so
 * this stays an SVG primitive rather than going through the insights charting stack.
 */
export function AnnotatedLineChart({
    viewWidth,
    viewHeight,
    series,
    annotations,
    baselineY,
    baselineLabel,
    xLabels,
    className,
}: AnnotatedLineChartProps): JSX.Element {
    return (
        <div className={className}>
            <svg viewBox={`0 0 ${viewWidth} ${viewHeight}`} className="block w-full h-auto" aria-hidden>
                {baselineY !== undefined ? (
                    <>
                        <line
                            x1={0}
                            y1={baselineY}
                            x2={viewWidth}
                            y2={baselineY}
                            stroke="var(--color-border-primary)"
                            strokeWidth={1}
                            strokeDasharray="3 3"
                        />
                        {baselineLabel ? (
                            <text
                                x={0}
                                y={baselineY - 4}
                                fontSize={9}
                                className="font-mono"
                                fill="var(--color-text-tertiary)"
                            >
                                {baselineLabel}
                            </text>
                        ) : null}
                    </>
                ) : null}
                {annotations?.map((annotation) => (
                    <g key={`${annotation.x}-${annotation.label}`}>
                        <line
                            x1={annotation.x}
                            y1={8}
                            x2={annotation.x}
                            y2={viewHeight - 12}
                            stroke={CHART_COLOR[annotation.color]}
                            strokeWidth={1.2}
                            strokeDasharray="4 3"
                        />
                        <text
                            x={annotation.labelAnchor === 'end' ? annotation.x - 6 : annotation.x + 6}
                            y={16}
                            fontSize={9.5}
                            textAnchor={annotation.labelAnchor === 'end' ? 'end' : 'start'}
                            fill={CHART_COLOR[annotation.color]}
                        >
                            {annotation.label}
                        </text>
                    </g>
                ))}
                {series.map((line, index) => (
                    <polyline
                        key={index}
                        points={line.points}
                        fill="none"
                        stroke={CHART_COLOR[line.color]}
                        strokeWidth={line.strokeWidth ?? 1.8}
                        strokeDasharray={line.dashed ? '4 3' : undefined}
                    />
                ))}
            </svg>
            {xLabels?.length ? (
                <div className="flex justify-between font-mono text-[10px] text-tertiary">
                    {xLabels.map((label) => (
                        <span key={label}>{label}</span>
                    ))}
                </div>
            ) : null}
        </div>
    )
}
