import { AnyPropertyFilter, PropertyFilterType } from '~/types'

/**
 * Detects a `wait_until_condition` condition that only the clock could ever satisfy.
 *
 * A wait is woken when a message arrives on one of its streams: an event, a person change, an
 * internal event, a distinct_id repoint. A condition that compares against the clock produces no
 * message at all, so nothing wakes it, and the API refuses it at save time. Finding it while the
 * step is built is what turns that refusal into guidance.
 *
 * Mirrors `find_clock_function` in
 * products/workflows/backend/services/wait_clock_conditions.py.
 */

// Zero-argument functions whose value advances with wall-clock time. A condition built on one of
// these changes truth value without anything happening, which is exactly what no stream can report.
const CLOCK_CALL = /(?:^|[^\w.])(now|today)\s*\(/

// A quoted literal can hold text that reads like a call, so it is blanked before the search.
const QUOTED_LITERAL = /'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`/g

type ConditionFilters = {
    properties?: unknown[]
    events?: { properties?: unknown[] }[]
    actions?: { properties?: unknown[] }[]
} | null

/** Name of the first clock function the condition calls, or null if it calls none. */
export function findClockFunction(filters?: ConditionFilters): string | null {
    const propertyGroups = [
        filters?.properties,
        ...(filters?.events ?? []).map((entry) => entry?.properties),
        ...(filters?.actions ?? []).map((entry) => entry?.properties),
    ]

    for (const properties of propertyGroups) {
        for (const property of (properties ?? []) as AnyPropertyFilter[]) {
            // Only a HogQL expression carries a function call; every other filter type is a
            // key/operator/value the compiler renders without touching the clock.
            if (property?.type !== PropertyFilterType.HogQL || typeof property.key !== 'string') {
                continue
            }
            const match = CLOCK_CALL.exec(property.key.replace(QUOTED_LITERAL, "''"))
            if (match) {
                return match[1]
            }
        }
    }

    return null
}

export function clockConditionError(clockFunction: string): string {
    return (
        `This condition uses ${clockFunction}(), so it depends on the current time. Nothing tells the workflow ` +
        'when that time arrives, so the wait runs until it times out. To wait for a point in time, use a delay ' +
        'step, then put this condition on the step after it.'
    )
}
