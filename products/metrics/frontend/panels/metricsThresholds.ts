import type { MetricsThreshold } from '~/queries/schema/schema-general'

/** Resolve the threshold color for a value. Thresholds are sorted by `value` at read
 * time, so the order a user enters them does not matter. The lowest step is the base
 * color below every other step; `null` (no data) returns `fallback`. */
export function thresholdColor(
    value: number | null,
    thresholds: MetricsThreshold[] | undefined,
    fallback: string
): string {
    if (value === null || !thresholds || thresholds.length === 0) {
        return fallback
    }
    const sorted = [...thresholds].sort((a, b) => a.value - b.value)
    let color = sorted[0].color
    for (const step of sorted) {
        if (value >= step.value) {
            color = step.color
        } else {
            break
        }
    }
    return color
}

/** A threshold color is persisted user input that ends up inside a class string;
 * anything beyond a plain token (whitespace, parentheses) could inject extra
 * utilities, so it falls back instead. */
export function safeColorToken(color: string, fallback: string): string {
    return /^[a-zA-Z0-9_-]+$/.test(color) ? color : fallback
}
