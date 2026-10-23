/** Helpers for walking arbitrary parsed JSON, where any key or shape is possible. */

export function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function hasKey(obj: Record<string, unknown> | null | undefined, key: string): boolean {
    return !!obj && Object.prototype.hasOwnProperty.call(obj, key)
}

/**
 * Serializes with object keys sorted. Two parsed JSON values that isDeepStrictEqual treats as equal
 * give the same string.
 */
export function canonicalJson(value: unknown): string {
    const sortKeys = (_key: string, nested: unknown): unknown =>
        isRecord(nested)
            ? Object.fromEntries(Object.entries(nested).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
            : nested
    return JSON.stringify(value, sortKeys) ?? 'undefined'
}

/**
 * Assign a key without triggering the inherited `__proto__` setter. Parsed JSON
 * can legitimately carry an own `__proto__` key (e.g. a tool payload being
 * debugged); a plain `out[key] = v` would set the target's prototype instead of
 * creating an own property, and drop the value from serialization.
 */
export function assignKey(target: Record<string, unknown>, key: string, value: unknown): void {
    if (key === '__proto__') {
        Object.defineProperty(target, key, { value, enumerable: true, writable: true, configurable: true })
    } else {
        target[key] = value
    }
}
