import { AnyPropertyFilter, PropertyFilterType } from '~/types'

/**
 * Detects a `wait_until_condition` condition that only the clock could ever satisfy.
 *
 * A wait is woken when a message arrives on one of its streams: an event, a person change, an
 * internal event, a distinct_id repoint. A condition that compares against the clock produces no
 * message at all, so no stream wakes it, and only the periodic re-check can advance it. The API
 * refuses it at save time. Finding it while the step is built is what turns that refusal into
 * guidance.
 *
 * Mirrors `find_clock_function` in
 * products/workflows/backend/services/wait_clock_conditions.py.
 */

// Zero-argument functions whose value advances with wall-clock time. A condition built on one of
// these changes truth value without anything happening, which is exactly what no stream can report.
const CLOCK_CALL = /(?:^|[^\w.])(now|today)\s*\(/

// Compiled from the author's filters rather than written by them, so comparing them would make an
// unchanged condition look edited. Mirrors `_DERIVED_FILTER_KEYS` in the API.
const DERIVED_FILTER_KEYS = ['bytecode', 'bytecode_error', 'source']

type ConditionFilters = {
    properties?: unknown[]
    events?: { properties?: unknown[] }[]
    actions?: { properties?: unknown[] }[]
} | null

type WaitCondition = { filters?: ConditionFilters } | null | undefined

/**
 * The expression with everything the parser does not read as code taken out: comments, and the text
 * of a plain string. An f-string keeps the expressions inside its braces, because the parser reads
 * those. Without this the search reports a call written in a comment or a literal, and misses one
 * written around a comment.
 */
function codeOnly(expression: string): string {
    let code = ''
    let index = 0

    while (index < expression.length) {
        const char = expression[index]

        if (char === '/' && expression[index + 1] === '*') {
            const end = expression.indexOf('*/', index + 2)
            index = end === -1 ? expression.length : end + 2
            code += ' '
        } else if (char === '-' && expression[index + 1] === '-') {
            const end = expression.indexOf('\n', index)
            index = end === -1 ? expression.length : end
            code += ' '
        } else if (char === "'" || char === '"' || char === '`') {
            const isTemplate = /(?:^|[^\w])[fF]$/.test(code)
            let body = ''
            index += 1
            while (index < expression.length && expression[index] !== char) {
                if (expression[index] === '\\') {
                    index += 1
                }
                body += expression[index] ?? ''
                index += 1
            }
            index += 1
            code += isTemplate ? ` ${templateExpressions(body)} ` : " '' "
        } else {
            code += char
            index += 1
        }
    }

    return code
}

/** The parts of an f-string body the parser evaluates, which is what sits between the braces. */
function templateExpressions(body: string): string {
    return (body.match(/\{[^{}]*\}/g) ?? []).join(' ')
}

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
            const match = CLOCK_CALL.exec(codeOnly(property.key))
            if (match) {
                return match[1]
            }
        }
    }

    return null
}

/** The parts of a wait condition a person wrote, with compiler output dropped. */
export function authoredCondition(condition: WaitCondition): unknown {
    const filters = condition?.filters
    if (!filters) {
        return condition
    }
    const authoredFilters = Object.fromEntries(
        Object.entries(filters).filter(([key]) => !DERIVED_FILTER_KEYS.includes(key))
    )
    return { ...condition, filters: authoredFilters }
}

export function clockConditionMessage(clockFunction: string): string {
    return (
        `This condition uses ${clockFunction}(), so it depends on the current time rather than on ` +
        'something happening, and it can only advance once the workflow checks it again. To wait for a point ' +
        'in time, use a delay step, then put this condition on the step after it.'
    )
}
