import { CSSProperties, SVGAttributes } from 'react'

const NAMES = [
    'paper',
    'ink',
    'night',
    'dusk',
    'snow',
    'shade',
    'ice',
    'pine',
    'gold',
    'glow',
    'red',
    'blue',
    'wood',
    'timber',
    'ember',
    'wall',
] as const

export type AdventPaletteColor = (typeof NAMES)[number]
export type AdventPalette = Record<AdventPaletteColor, string>

function token(name: string): string {
    return getComputedStyle(document.body).getPropertyValue(name).trim()
}

function mix(color: string, share: number, other: string): string {
    return `color-mix(in oklab, ${color} ${share}%, ${other})`
}

let cached: AdventPalette | null = null

export function adventPalette(): AdventPalette {
    if (cached) {
        return cached
    }
    const blue = token('--brand-blue')
    const red = token('--brand-red')
    const yellow = token('--brand-yellow')
    const paper = mix(yellow, 12, 'white')
    const ink = mix(blue, 30, 'black')
    const night = mix(blue, 58, 'black')
    const gold = mix(yellow, 88, red)
    const wood = mix(mix(red, 50, yellow), 52, ink)
    cached = {
        paper,
        ink,
        night,
        dusk: mix(night, 62, paper),
        snow: mix(blue, 4, 'white'),
        shade: mix(blue, 20, 'white'),
        ice: mix(blue, 36, 'white'),
        pine: mix(token('--success'), 48, ink),
        gold,
        glow: mix(gold, 32, 'transparent'),
        red: mix(red, 82, ink),
        blue: mix(blue, 62, paper),
        wood,
        timber: mix(wood, 55, ink),
        ember: mix(red, 70, yellow),
        wall: mix(wood, 26, paper),
    }
    return cached
}

export function adventPaletteStyle(): CSSProperties {
    const palette = adventPalette()
    return Object.fromEntries(NAMES.map((name) => [`--advent-${name}`, palette[name]])) as CSSProperties
}

export function adventStroke(color: string, width = 2.5): SVGAttributes<SVGElement> {
    return { fill: 'none', stroke: color, strokeWidth: width, strokeLinecap: 'round', strokeLinejoin: 'round' }
}
