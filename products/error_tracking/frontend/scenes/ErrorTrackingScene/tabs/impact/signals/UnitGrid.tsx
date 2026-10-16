import { useImpactPalette } from './useImpactPalette'

// A waffle of units: `filled` units in the lens color out of `total`, so a share reads as a count of things.
export function UnitGrid({
    total,
    filled,
    columns,
    color,
    size = 7,
    gap = 2,
    shape = 'square',
}: {
    total: number
    filled: number
    columns: number
    color: string
    size?: number
    gap?: number
    shape?: 'square' | 'circle'
}): JSX.Element {
    const palette = useImpactPalette()
    const rows = Math.ceil(total / columns)
    const step = size + gap
    return (
        <svg width={columns * step - gap} height={rows * step - gap} className="block shrink-0" aria-hidden>
            {Array.from({ length: total }, (_, index) => {
                const x = (index % columns) * step
                const yPos = Math.floor(index / columns) * step
                const fill = index < Math.round(filled) ? color : palette.neutral
                return shape === 'circle' ? (
                    <circle key={index} cx={x + size / 2} cy={yPos + size / 2} r={size / 2} fill={fill} />
                ) : (
                    <rect key={index} x={x} y={yPos} width={size} height={size} rx={1.5} fill={fill} />
                )
            })}
        </svg>
    )
}
