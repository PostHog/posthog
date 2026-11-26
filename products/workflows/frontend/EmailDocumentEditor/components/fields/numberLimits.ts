export interface NumberLimit {
    min: number
    max: number
}

export const NUMBER_LIMITS = {
    bodyWidth: { min: 200, max: 1200 },
    imageWidth: { min: 1, max: 1200 },
    padding: { min: 0, max: 200 },
    gap: { min: 0, max: 100 },
    // 999 is the usual way to ask for fully rounded ends.
    cornerRadius: { min: 0, max: 999 },
    border: { min: 0, max: 20 },
    dividerThickness: { min: 1, max: 20 },
    spacerHeight: { min: 1, max: 400 },
    textSize: { min: 8, max: 96 },
    baseTextSize: { min: 8, max: 40 },
    lineHeight: { min: 80, max: 300 },
    letterSpacing: { min: -10, max: 20 },
    percent: { min: 1, max: 100 },
} satisfies Record<string, NumberLimit>

export function clampNumber(value: number, { min, max }: NumberLimit): number {
    return Math.min(max, Math.max(min, value))
}
