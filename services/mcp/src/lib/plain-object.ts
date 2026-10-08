/** Helpers for walking arbitrary parsed JSON, where any key or shape is possible. */

export function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
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
