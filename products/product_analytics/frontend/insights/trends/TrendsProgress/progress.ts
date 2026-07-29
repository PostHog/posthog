import type { GoalLine } from '~/queries/schema/schema-general'

export interface ProgressTarget {
    label: string
    value: number
    color?: string
}

/**
 * The progress display has no axis to overlay a goal line on, so it reuses the goal line as its
 * target instead of adding a second concept to the schema. Only the first usable one counts.
 */
export function selectProgressTarget(goalLines: GoalLine[] | undefined | null): ProgressTarget | null {
    const goalLine = goalLines?.find((line) => Number.isFinite(line.value) && line.value > 0)
    if (!goalLine) {
        return null
    }
    return { label: goalLine.label, value: goalLine.value, color: goalLine.borderColor }
}

/** Share of the target reached. Can exceed 1 (target beaten) or go negative (formula insights). */
export function computeProgressFraction(value: number | null | undefined, target: number): number {
    if (value == null || !Number.isFinite(value) || target <= 0) {
        return 0
    }
    return value / target
}
