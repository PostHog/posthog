export const SPARKLINE_HEIGHT = 32

/** The shortest bar, so a zero still reads as a bar. */
export const SPARKLINE_MIN_BAR = 2

export function sparklineBarHeight(value: number, max: number, height: number = SPARKLINE_HEIGHT): number {
    if (!(max > 0) || !Number.isFinite(value)) {
        return SPARKLINE_MIN_BAR
    }
    const scaled = Math.round((value * height) / max)
    return Math.min(height, Math.max(SPARKLINE_MIN_BAR, scaled))
}
