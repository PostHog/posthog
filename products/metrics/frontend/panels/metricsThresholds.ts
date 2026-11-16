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

const THRESHOLD_COLOR_TOKENS = new Set([
    'success',
    'warning',
    'danger',
    'blue',
    'purple',
    ...Array.from({ length: 15 }, (_, index) => `data-color-${index + 1}`),
])
// The same Grafana names that `map_color` in the dashboard import maps. Dashboards saved before
// the import validated colors can still hold them.
const GRAFANA_COLOR_NAMES: [string, string][] = [
    ['green', 'success'],
    ['red', 'danger'],
    ['orange', 'warning'],
    ['yellow', 'warning'],
    ['blue', 'blue'],
    ['purple', 'purple'],
]

/** The threshold color for a value as a token that has a CSS variable. `getColorVar` captures an
 * exception for a missing variable, and the panels call it on every render and sparkline hover,
 * so an unknown stored color maps to a Grafana equivalent or to `fallback`. */
export function thresholdColorToken(
    value: number | null,
    thresholds: MetricsThreshold[] | undefined,
    fallback: string
): string {
    const color = thresholdColor(value, thresholds, fallback)
    if (THRESHOLD_COLOR_TOKENS.has(color)) {
        return color
    }
    const lowered = color.toLowerCase()
    return GRAFANA_COLOR_NAMES.find(([name]) => lowered.includes(name))?.[1] ?? fallback
}

/** A threshold color is persisted user input that ends up inside a class string;
 * anything beyond a plain token (whitespace, parentheses) could inject extra
 * utilities, so it falls back instead. */
export function safeColorToken(color: string, fallback: string): string {
    return /^[a-zA-Z0-9_-]+$/.test(color) ? color : fallback
}
