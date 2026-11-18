export type FadeCurve = 'linear' | 'smooth'

interface FadeStop {
    key: string
    offset: number
    opacity: number
}

const LINEAR_STOPS = [
    [0, 1],
    [1, 0],
] as const
// Keep the lower edge visible while adding strength through the upper half.
const SMOOTH_STOPS = [
    [0, 1],
    [0.2, 0.8768],
    [0.4, 0.6864],
    [0.6, 0.4576],
    [0.8, 0.2192],
    [1, 0],
] as const

export function fadeStops(solid: number, curve: FadeCurve): FadeStop[] {
    const stops = curve === 'smooth' ? SMOOTH_STOPS : LINEAR_STOPS
    return [
        { key: 'start', offset: 0, opacity: 1 },
        ...stops.map(([offset, opacity]) => ({
            key: `ramp-${offset}`,
            offset: solid + (1 - solid) * offset,
            opacity,
        })),
    ]
}
