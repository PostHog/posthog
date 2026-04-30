import type { BaselineSparklineDayApi } from '../generated/api.schemas'

const COLORS = {
    clean: 'var(--success)',
    tolerated: 'var(--primary-3000)',
    changed: 'var(--warning-dark)',
    quarantined: 'var(--danger)',
}

const EMPTY_TRACK = 'var(--border)'

// Cheap inline-SVG sparkline. ~30 stacked-segment columns, no Chart.js, no
// hover tooltips — designed to be cheap enough to render on every card in a
// virtualized grid. Each day is a single column; segments stack proportionally
// from the bottom.
export function InlineSparkline({
    data,
    className,
    title,
}: {
    data: BaselineSparklineDayApi[]
    className?: string
    title?: string
}): JSX.Element {
    const cols = data.length || 1
    const colWidth = 100 / cols
    const max = data.reduce((m, d) => Math.max(m, d.clean + d.tolerated + d.changed + d.quarantined), 0) || 1

    return (
        <svg
            viewBox="0 0 100 24"
            preserveAspectRatio="none"
            className={className ?? 'h-6 w-24'}
            role="img"
            aria-label={title ?? 'snapshot stability over the last 30 days'}
        >
            {data.map((day, i) => {
                const total = day.clean + day.tolerated + day.changed + day.quarantined
                const x = i * colWidth + colWidth * 0.1
                const w = colWidth * 0.8
                if (total === 0) {
                    return <rect key={i} x={x} y={22} width={w} height={1} fill={EMPTY_TRACK} />
                }
                const segments = [
                    { value: day.quarantined, color: COLORS.quarantined },
                    { value: day.changed, color: COLORS.changed },
                    { value: day.tolerated, color: COLORS.tolerated },
                    { value: day.clean, color: COLORS.clean },
                ]
                let yCursor = 24
                return (
                    <g key={i}>
                        {segments.map((s, j) => {
                            if (s.value === 0) {
                                return null
                            }
                            const h = (s.value / max) * 22
                            yCursor -= h
                            return <rect key={j} x={x} y={yCursor} width={w} height={h} fill={s.color} />
                        })}
                    </g>
                )
            })}
        </svg>
    )
}
