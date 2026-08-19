/**
 * Tiny occurrence-volume bar strip for the demo report evidence cards.
 * Bars before `alarmFromIndex` render muted (baseline); the rest render in the
 * danger tint to show the regression window.
 */
export function DemoBarStrip({
    values,
    alarmFromIndex = 0,
    height = 40,
    barWidth = 5,
    gap = 10,
    className,
}: {
    values: number[]
    alarmFromIndex?: number
    height?: number
    barWidth?: number
    gap?: number
    className?: string
}): JSX.Element {
    const viewWidth = values.length * (barWidth + gap)
    return (
        <svg
            viewBox={`0 0 ${viewWidth} ${height + 2}`}
            className={`block w-full h-auto ${className ?? ''}`}
            aria-hidden
        >
            {values.map((value, index) => (
                <rect
                    key={index}
                    x={index * (barWidth + gap)}
                    y={height - value}
                    width={barWidth}
                    height={value}
                    rx={1}
                    fill={index < alarmFromIndex ? 'var(--color-border-primary)' : 'var(--danger-lighter)'}
                />
            ))}
        </svg>
    )
}
