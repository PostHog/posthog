/** Scratch prototype data for v2: invented daily cumulative delta and interval per variant. */
import { EXPOSURES, type PrototypeMetric, type PrototypeVariantResult } from './prototypeData'

export interface VariantTrend {
    key: string
    delta: number[]
    lower: number[]
    upper: number[]
}

/** Deterministic wobble so every render draws the same picture. */
function wobble(seed: number, day: number): number {
    return Math.sin(seed * 1.7 + day * 0.55) * 0.7 + Math.sin(seed * 0.9 + day * 0.25) * 0.3
}

function seedOf(text: string): number {
    return [...text].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 97
}

function variantTrend(metricName: string, variant: PrototypeVariantResult, days: number): VariantTrend | null {
    if (variant.delta === null || variant.interval === null) {
        return null
    }
    const finalDelta = variant.delta
    const halfWidth = (variant.interval[1] - variant.interval[0]) / 2
    const seed = seedOf(`${metricName}-${variant.key}`)
    const delta: number[] = []
    const lower: number[] = []
    const upper: number[] = []
    for (let day = 1; day <= days; day++) {
        const spread = halfWidth * Math.sqrt(days / day)
        const center = day === days ? finalDelta : finalDelta + wobble(seed, day) * spread * 0.35 * (1 - day / days)
        delta.push(center)
        lower.push(center - spread)
        upper.push(center + spread)
    }
    return { key: variant.key, delta, lower, upper }
}

export function metricTrends(metric: PrototypeMetric): VariantTrend[] {
    return metric.variants
        .map((variant) => variantTrend(metric.name, variant, EXPOSURES.days.length))
        .filter((trend): trend is VariantTrend => trend !== null)
}
