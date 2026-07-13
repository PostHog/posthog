/**
 * Stable stringify, sha256 helpers, and the sentinel <-> `$planRef`
 * normalization/substitution primitives shared by the plan builder and the
 * enforcer. Kept in one file so the `$planRef` marker encoding has a single
 * owner: normalization (plan build) and substitution (apply) must agree byte
 * for byte or matching silently breaks.
 */

import { createHash } from 'node:crypto'

import { isPlanRef, type NormalizedMutation, type PlanRef } from './types'

/** A sentinel value with its originating mutation, for normalization. */
export interface IssuedSentinel {
    sequence: number
    field: string
    value: string | number
}

/**
 * Deterministic JSON with object keys sorted recursively and arrays kept in
 * order. Two values that differ only in key order stringify identically, so
 * this doubles as an order-independent structural comparison and as the hash
 * pre-image.
 */
export function stableStringify(value: unknown): string {
    return JSON.stringify(sortValue(value))
}

function sortValue(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(sortValue)
    }
    if (typeof value === 'object' && value !== null) {
        const input = value as Record<string, unknown>
        const output: Record<string, unknown> = {}
        for (const key of Object.keys(input).sort()) {
            output[key] = sortValue(input[key])
        }
        return output
    }
    return value
}

/** Structural equality via canonical stringify — type- and array-order-sensitive. */
export function deepEqualCanonical(a: unknown, b: unknown): boolean {
    return stableStringify(a) === stableStringify(b)
}

export function sha256Hex(input: string): string {
    return createHash('sha256').update(input, 'utf8').digest('hex')
}

// A NUL delimiter keeps the marker disjoint from any JSON content a script
// emits. Built via fromCharCode so the source file stays plain ASCII.
const REF_DELIM = String.fromCharCode(0)
const REF_PREFIX = `${REF_DELIM}$planRef:`
const REF_SUFFIX = REF_DELIM

function refToken(sequence: number, field: string): string {
    return `${REF_PREFIX}${sequence}:${field}${REF_SUFFIX}`
}

function bindingKey(sequence: number, field: string): string {
    return `${sequence}:${field}`
}

// Longer textual forms first so a shorter sentinel can't shadow a longer one
// that contains it as a substring.
function byTextLengthDesc(a: IssuedSentinel, b: IssuedSentinel): number {
    return String(b.value).length - String(a.value).length
}

/** Replace every issued sentinel occurrence in a path string with its marker. */
export function normalizePath(path: string, sentinels: IssuedSentinel[]): string {
    let result = path
    for (const sentinel of [...sentinels].sort(byTextLengthDesc)) {
        const text = String(sentinel.value)
        if (result.includes(text)) {
            result = result.split(text).join(refToken(sentinel.sequence, sentinel.field))
        }
    }
    return result
}

/**
 * Replace sentinels in an arbitrary JSON value. A value that *is* a sentinel
 * becomes a `$planRef` object (preserving numeric typing); a string that merely
 * *contains* a sentinel gets the marker substituted textually.
 */
export function normalizeValue(value: unknown, sentinels: IssuedSentinel[]): unknown {
    if (typeof value === 'number') {
        const exact = sentinels.find((s) => s.value === value)
        return exact ? planRef(exact) : value
    }
    if (typeof value === 'string') {
        const exact = sentinels.find((s) => s.value === value)
        if (exact) {
            return planRef(exact)
        }
        let result = value
        for (const sentinel of [...sentinels].sort(byTextLengthDesc)) {
            const text = String(sentinel.value)
            if (result.includes(text)) {
                result = result.split(text).join(refToken(sentinel.sequence, sentinel.field))
            }
        }
        return result
    }
    if (Array.isArray(value)) {
        return value.map((item) => normalizeValue(item, sentinels))
    }
    if (typeof value === 'object' && value !== null) {
        const input = value as Record<string, unknown>
        const output: Record<string, unknown> = {}
        for (const key of Object.keys(input)) {
            output[key] = normalizeValue(input[key], sentinels)
        }
        return output
    }
    return value
}

function planRef(sentinel: IssuedSentinel): PlanRef {
    return { $planRef: { sequence: sentinel.sequence, field: sentinel.field } }
}

/** Substitute captured real values back into a normalized path. */
export function substituteRefsInPath(path: string, bindings: Map<string, string | number>): string {
    let result = path
    for (const [key, value] of bindings) {
        const token = `${REF_PREFIX}${key}${REF_SUFFIX}`
        if (result.includes(token)) {
            result = result.split(token).join(String(value))
        }
    }
    return result
}

/** Substitute captured real values back into a normalized body. */
export function substituteRefsInBody(value: unknown, bindings: Map<string, string | number>): unknown {
    if (isPlanRef(value)) {
        const key = bindingKey(value.$planRef.sequence, value.$planRef.field)
        return bindings.has(key) ? bindings.get(key) : value
    }
    if (typeof value === 'string') {
        let result = value
        for (const [key, bound] of bindings) {
            const token = `${REF_PREFIX}${key}${REF_SUFFIX}`
            if (result.includes(token)) {
                result = result.split(token).join(String(bound))
            }
        }
        return result
    }
    if (Array.isArray(value)) {
        return value.map((item) => substituteRefsInBody(item, bindings))
    }
    if (typeof value === 'object' && value !== null) {
        const input = value as Record<string, unknown>
        const output: Record<string, unknown> = {}
        for (const key of Object.keys(input)) {
            output[key] = substituteRefsInBody(input[key], bindings)
        }
        return output
    }
    return value
}

/**
 * Hash the confirmed mutation content — method, normalized path, normalized
 * body per entry, in order. Ordering of object keys within a body does not
 * affect the hash (stable stringify), so two runs producing the same mutations
 * in the same order hash identically regardless of serialization order.
 */
export function computePlanHash(mutations: NormalizedMutation[]): string {
    const canonical = mutations.map((m) => ({ method: m.method, path: m.path, body: m.body }))
    return sha256Hex(stableStringify(canonical))
}

export function computeScriptHash(source: string): string {
    return sha256Hex(source)
}
