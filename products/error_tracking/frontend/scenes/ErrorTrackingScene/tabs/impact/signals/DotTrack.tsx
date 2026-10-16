import { useImpactPalette } from './useImpactPalette'

const pct = (value: number): string => `${Math.min(Math.max(value, 0), 1) * 100}%`

export interface TrackPoint {
    value: number
    color: string
    radius?: number
}

// Points on a 0 to 100% track, optionally joined by a band from one point to the other.
export function DotTrack({
    points,
    join,
    height = 12,
}: {
    points: TrackPoint[]
    join?: { from: number; to: number; color: string; opacity?: number }
    height?: number
}): JSX.Element {
    const palette = useImpactPalette()
    const y = height / 2
    return (
        <svg className="block w-full overflow-visible" height={height} aria-hidden>
            <line x1="0" x2="100%" y1={y} y2={y} stroke={palette.neutral} strokeWidth={2} />
            {join && (
                <line
                    x1={pct(join.from)}
                    x2={pct(join.to)}
                    y1={y}
                    y2={y}
                    stroke={join.color}
                    strokeOpacity={join.opacity ?? 0.45}
                    strokeWidth={4}
                />
            )}
            {points.map((point, index) => (
                <circle
                    key={index}
                    cx={pct(point.value)}
                    cy={y}
                    r={point.radius ?? 4.5}
                    fill={point.color}
                    stroke={palette.surface}
                    strokeWidth={2}
                />
            ))}
        </svg>
    )
}
