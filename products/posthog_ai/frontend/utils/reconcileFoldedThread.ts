import type { ThreadItem, ToolInvocation } from '../types/streamTypes'

const MAX_COMPARE_DEPTH = 4

function isPlainObject(value: object): value is Record<string, unknown> {
    const proto = Object.getPrototypeOf(value)
    return proto === Object.prototype || proto === null
}

function sameValue(a: unknown, b: unknown, depth: number): boolean {
    if (a === b) {
        return true
    }
    if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) {
        return a !== a && b !== b
    }
    if (depth <= 0) {
        return false
    }
    if (Array.isArray(a)) {
        if (!Array.isArray(b) || a.length !== b.length) {
            return false
        }
        for (let index = 0; index < a.length; index++) {
            if (!sameValue(a[index], b[index], depth - 1)) {
                return false
            }
        }
        return true
    }
    if (Array.isArray(b) || !isPlainObject(a) || !isPlainObject(b)) {
        return false
    }
    return sameRecord(a, b, depth)
}

function sameRecord(a: Record<string, unknown>, b: Record<string, unknown>, depth: number): boolean {
    let keyCount = 0
    for (const key in a) {
        keyCount++
        if (!(key in b) || !sameValue(a[key], b[key], depth - 1)) {
            return false
        }
    }
    for (const _key in b) {
        keyCount--
    }
    return keyCount === 0
}

function reuse<T>(previous: T | undefined, next: T): T {
    return previous !== undefined && sameValue(previous, next, MAX_COMPARE_DEPTH) ? previous : next
}

export function reconcileThreadItems(previous: ThreadItem[] | undefined, next: ThreadItem[]): ThreadItem[] {
    if (!previous || previous.length === 0) {
        return next
    }
    const previousById = new Map<string, ThreadItem>()
    for (const item of previous) {
        previousById.set(item.id, item)
    }
    let unchanged = previous.length === next.length
    const result = next.map((item, index) => {
        const kept = reuse(previousById.get(item.id), item)
        if (unchanged && kept !== previous[index]) {
            unchanged = false
        }
        return kept
    })
    return unchanged ? previous : result
}

export function reconcileToolInvocations(
    previous: Map<string, ToolInvocation> | undefined,
    next: Map<string, ToolInvocation>
): Map<string, ToolInvocation> {
    if (!previous || previous.size === 0) {
        return next
    }
    let unchanged = previous.size === next.size
    const result = new Map<string, ToolInvocation>()
    for (const [id, invocation] of next) {
        const previousInvocation = previous.get(id)
        const kept = reuse(previousInvocation, invocation)
        if (unchanged && kept !== previousInvocation) {
            unchanged = false
        }
        result.set(id, kept)
    }
    return unchanged ? previous : result
}
