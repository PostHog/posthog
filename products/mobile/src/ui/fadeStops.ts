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
// Smoothstep samples soften the lower edge and strengthen the upper half.
const SMOOTH_STOPS = [
    [0, 1],
    [0.2, 0.896],
    [0.4, 0.648],
    [0.6, 0.352],
    [0.8, 0.104],
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
