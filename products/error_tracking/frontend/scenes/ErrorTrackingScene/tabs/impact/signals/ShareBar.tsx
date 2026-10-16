import { useImpactPalette } from './useImpactPalette'

export interface ShareBarProps {
    // Share of the whole, from 0 to 1.
    value: number
    color: string
    // A thin tick across the bar, for a baseline the value is compared with.
    marker?: number
    height?: number
}

const MIN_VISIBLE_SHARE = 0.005

const percent = (value: number): string => `${Math.min(Math.max(value, 0), 1) * 100}%`

export function ShareBar({ value, color, marker, height = 6 }: ShareBarProps): JSX.Element {
    const palette = useImpactPalette()
    const radius = height / 2
    return (
        <svg className="block w-full overflow-visible" height={height} aria-hidden>
            <rect width="100%" height={height} rx={radius} fill={palette.neutral} fillOpacity={0.45} />
            {value > 0 && (
                <rect width={percent(Math.max(value, MIN_VISIBLE_SHARE))} height={height} rx={radius} fill={color} />
            )}
            {marker !== undefined && (
                <rect
                    x={percent(marker)}
                    y={-3}
                    width={2}
                    height={height + 6}
                    rx={1}
                    fill={palette.ink}
                    transform="translate(-1 0)"
                />
            )}
        </svg>
    )
}
