/**
 * Sentinel synthesis for plan mode. When a create is intercepted its identifier
 * fields must return *something* so the script can keep going and reveal its
 * downstream mutations. Sentinels are schema-correct primitives (a numeric id
 * gets a reserved-range negative integer, a string id a distinctive token), so
 * a script that does `Number(created.id)` sees a number, not `NaN` — killing the
 * silent-type-lie class of plan corruption. They are globally unique within an
 * execution, which is what makes later textual substitution sound.
 */

import type { IssuedSentinel } from './hashes'
import type { IdField, SentinelAssignment } from './types'

/** Reserved negative range start; decrements per numeric sentinel issued. */
const NUMERIC_SENTINEL_START = -900001

export interface SentinelFactory {
    /** Opaque execution identifier this factory issues sentinels for. */
    readonly executionId: string
    /** Issue a sentinel for `field` in the response to the mutation at `sequence`. */
    issue(sequence: number, field: IdField): SentinelAssignment
    /** Every sentinel issued so far, in issue order. */
    issued(): IssuedSentinel[]
}

export function createSentinelFactory(executionId: string): SentinelFactory {
    let nextNumeric = NUMERIC_SENTINEL_START
    const issued: IssuedSentinel[] = []
    return {
        executionId,
        issue(sequence, field) {
            const value = field.type === 'number' ? nextNumeric-- : `__ph_plan_${sequence}_${field.name}__`
            issued.push({ sequence, field: field.name, value })
            return { field: field.name, value }
        },
        issued() {
            return [...issued]
        },
    }
}

/**
 * Deep-scan any JSON value (including substrings of strings, array items, and
 * object values) for issued sentinel values. Returns the matched sentinels.
 */
export function findSentinelRefs(value: unknown, issued: IssuedSentinel[]): IssuedSentinel[] {
    const matched = new Map<string, IssuedSentinel>()
    scan(value, issued, matched)
    return [...matched.values()]
}

function scan(value: unknown, issued: IssuedSentinel[], matched: Map<string, IssuedSentinel>): void {
    if (typeof value === 'number') {
        for (const sentinel of issued) {
            if (sentinel.value === value) {
                matched.set(`${sentinel.sequence}:${sentinel.field}`, sentinel)
            }
        }
        return
    }
    if (typeof value === 'string') {
        for (const sentinel of issued) {
            if (value.includes(String(sentinel.value))) {
                matched.set(`${sentinel.sequence}:${sentinel.field}`, sentinel)
            }
        }
        return
    }
    if (Array.isArray(value)) {
        for (const item of value) {
            scan(item, issued, matched)
        }
        return
    }
    if (typeof value === 'object' && value !== null) {
        for (const item of Object.values(value)) {
            scan(item, issued, matched)
        }
    }
}
