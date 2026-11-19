import type { ThemeColors } from '@/ui/theme'

/** The web's floor, so the country with the fewest visitors still reads as blue and not as empty land. */
const FLOOR = 0.3

function channels(hex: string): number[] | null {
    const digits = /^#([0-9a-f]{6})$/i.exec(hex)?.[1]
    if (!digits) {
        return null
    }
    const value = Number.parseInt(digits, 16)
    return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

/**
 * A country's fill: the land color mixed toward blue by `ratio`, the country's visitors over the leading country's.
 * The web draws blue at that opacity over the land; an opaque mix gives the same color and keeps borders crisp.
 */
export function mapFill(colors: Pick<ThemeColors, 'segmentEmpty' | 'blue'>, ratio: number): string {
    const land = channels(colors.segmentEmpty)
    const blue = channels(colors.blue)
    if (!land || !blue) {
        return colors.blue
    }
    const clamped = Number.isFinite(ratio) ? Math.min(1, Math.max(0, ratio)) : 0
    const strength = FLOOR + (1 - FLOOR) * clamped
    const mixed = land.map((from, index) => Math.round(from + ((blue[index] ?? from) - from) * strength))
    return `#${mixed.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`
}
