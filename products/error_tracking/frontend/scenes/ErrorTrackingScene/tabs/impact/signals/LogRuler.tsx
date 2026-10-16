import { useImpactPalette } from './useImpactPalette'

const pct = (value: number): string => `${Math.min(Math.max(value, 0), 1) * 100}%`

// A log scale for rates that differ by orders of magnitude, with a tick at every power of ten.
export function LogRuler({
    min,
    max,
    markers,
    height = 18,
}: {
    min: number
    max: number
    markers: { value: number; color: string; radius?: number }[]
    height?: number
}): JSX.Element {
    const palette = useImpactPalette()
    const lo = Math.log10(min)
    const hi = Math.log10(max)
    const at = (value: number): string => pct((Math.log10(Math.max(value, min)) - lo) / (hi - lo))
    const decades = Array.from({ length: Math.round(hi - lo) + 1 }, (_, index) => 10 ** (lo + index))
    const y = height / 2
    return (
        <svg className="block w-full overflow-visible" height={height} aria-hidden>
            <line x1="0" x2="100%" y1={y} y2={y} stroke={palette.neutral} strokeWidth={2} />
            {decades.map((decade) => (
                <line
                    key={decade}
                    x1={at(decade)}
                    x2={at(decade)}
                    y1={y - 4}
                    y2={y + 4}
                    stroke={palette.neutral}
                    strokeWidth={1}
                />
            ))}
            {markers.map((marker, index) => (
                <circle
                    key={index}
                    cx={at(marker.value)}
                    cy={y}
                    r={marker.radius ?? 5}
                    fill={marker.color}
                    stroke={palette.surface}
                    strokeWidth={2}
                />
            ))}
        </svg>
    )
}
