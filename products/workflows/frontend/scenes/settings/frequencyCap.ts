// Kept in step with the max_value on TeamWorkflowsConfigSerializer.
export const MAX_FREQUENCY_CAP_MESSAGES = 1000
export const MAX_FREQUENCY_CAP_WINDOW_DAYS = 30
export const MAX_FREQUENCY_CAP_HOLD_HOURS = 168

export function frequencyCapHoldError(value: number | null): string | undefined {
    return value === null || (Number.isInteger(value) && value >= 1 && value <= MAX_FREQUENCY_CAP_HOLD_HOURS)
        ? undefined
        : `Enter a whole number from 1 to ${MAX_FREQUENCY_CAP_HOLD_HOURS}, or leave it empty`
}

// A cleared number input reports NaN, which must save as null to turn the cap off.
export function toFrequencyCapInputValue(value: number | null | undefined): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function frequencyCapFieldError(value: number | null, other: number | null, max: number): string | undefined {
    if (value === null) {
        return other === null ? undefined : 'Fill in both fields, or clear both to turn the cap off'
    }
    return Number.isInteger(value) && value >= 1 && value <= max
        ? undefined
        : `Enter a whole number from 1 to ${max.toLocaleString()}`
}
