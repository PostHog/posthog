import { DurationType, PropertyOperator, RecordingDurationFilter } from '~/types'

// Vision only analyzes recordings within these server-enforced duration bounds (see backend constants.py).
export const DURATION_BOUNDS: Partial<Record<DurationType, { min?: number; max?: number }>> = {
    duration: { min: 15 },
    active_seconds: { min: 10, max: 3600 },
}

// The hard ceiling Vision enforces on active interaction time — recordings above it are always skipped.
export const MAX_ACTIVE_SECONDS = DURATION_BOUNDS.active_seconds?.max ?? 3600
export const MAX_ACTIVE_LABEL = `${Math.round(MAX_ACTIVE_SECONDS / 3600)}h`

export function clampDurationFilter(filter: RecordingDurationFilter): RecordingDurationFilter {
    const bounds = DURATION_BOUNDS[filter.key]
    if (!bounds) {
        return filter
    }
    let value = Number(filter.value) || 0
    if (bounds.min != null) {
        value = Math.max(value, bounds.min)
    }
    if (bounds.max != null) {
        value = Math.min(value, bounds.max)
    }
    return value === filter.value ? filter : { ...filter, value }
}

// A duration filter that can't overlap Vision's scannable window [min, max] selects only recordings that
// are always skipped, so the scanner would produce nothing. Returns a human-readable reason for that case
// (e.g. "active time > 1h", which the ceiling always skips), else null. The value is assumed clamped.
export function durationFilterError(filter: RecordingDurationFilter | undefined): string | null {
    if (!filter) {
        return null
    }
    const bounds = DURATION_BOUNDS[filter.key]
    if (!bounds) {
        return null
    }
    const value = Number(filter.value) || 0
    if (bounds.max != null && filter.operator === PropertyOperator.GreaterThan && value >= bounds.max) {
        return `Vision skips recordings over ${MAX_ACTIVE_LABEL} of active time, so "greater than" this scans nothing. Lower the threshold or switch to "less than".`
    }
    if (bounds.min != null && filter.operator === PropertyOperator.LessThan && value <= bounds.min) {
        return `Vision skips recordings under ${bounds.min}s of active time, so "less than" this scans nothing. Raise the threshold or switch to "greater than".`
    }
    return null
}
