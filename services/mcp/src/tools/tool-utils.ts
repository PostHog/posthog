import type { Context } from '@/tools/types'

/** Adds a _posthogUrl field to any type. Use instead of `T & { _posthogUrl: string }`. */
export type WithPostHogUrl<T = unknown> = T & { _posthogUrl: string }

/** Adds _posthogUrl to a result object. */
export async function withPostHogUrl<T>(context: Context, result: T, path: string): Promise<WithPostHogUrl<T>> {
    const projectId = await context.stateManager.getProjectId()

    const baseUrl = context.api.getProjectBaseUrl(projectId)
    const fullUrl = `${baseUrl}${path}`

    return { ...result, _posthogUrl: fullUrl } as WithPostHogUrl<T>
}

/**
 * Pick only fields matching the given dot-path patterns.
 * Supports wildcards: `'groups.*.key'` iterates all array items / object keys.
 */
export function pickResponseFields<T>(obj: T, paths: string[]): Partial<T> {
    const result: Record<string, unknown> = {}
    for (const p of paths) {
        copyAtPath(obj, result, p.split('.'))
    }
    return result as Partial<T>
}

function copyAtPath(source: unknown, target: Record<string, unknown>, segments: string[]): void {
    if (source === null || source === undefined || typeof source !== 'object') {
        return
    }
    const [head, ...rest] = segments
    if (!head) {
        return
    }
    if (head === '*') {
        const src = source as Record<string, unknown>
        if (Array.isArray(source)) {
            const arr = target as unknown as unknown[]
            for (let i = 0; i < source.length; i++) {
                if (arr[i] === undefined) {
                    arr[i] = {}
                }
                if (rest.length === 0) {
                    arr[i] = structuredClone(source[i])
                } else {
                    copyAtPath(source[i], arr[i] as Record<string, unknown>, rest)
                }
            }
        } else {
            for (const key of Object.keys(src)) {
                if (target[key] === undefined) {
                    target[key] = {}
                }
                if (rest.length === 0) {
                    target[key] = structuredClone(src[key])
                } else {
                    copyAtPath(src[key], target[key] as Record<string, unknown>, rest)
                }
            }
        }
        return
    }
    const src = (source as Record<string, unknown>)[head]
    if (src === undefined) {
        return
    }
    if (rest.length === 0) {
        target[head] = structuredClone(src)
    } else {
        if (src === null || typeof src !== 'object') {
            return
        }
        if (target[head] === undefined) {
            target[head] = Array.isArray(src) ? [] : {}
        }
        copyAtPath(src, target[head] as Record<string, unknown>, rest)
    }
}

/**
 * Remove fields matching the given dot-path patterns.
 * Supports wildcards: `'groups.*.properties'` iterates all array items / object keys.
 */
export function omitResponseFields<T>(obj: T, paths: string[]): Partial<T> {
    const result = structuredClone(obj)
    for (const p of paths) {
        removeAtPath(result, p.split('.'))
    }
    return result as Partial<T>
}

function removeAtPath(obj: unknown, segments: string[]): void {
    if (obj === null || obj === undefined || typeof obj !== 'object') {
        return
    }
    const [head, ...rest] = segments
    if (!head) {
        return
    }
    if (head === '*') {
        const items = Array.isArray(obj) ? obj : Object.values(obj)
        for (const item of items) {
            if (rest.length === 0) {
                // Wildcard at leaf makes no sense for omit — skip
            } else {
                removeAtPath(item, rest)
            }
        }
        return
    }
    const record = obj as Record<string, unknown>
    if (rest.length === 0) {
        delete record[head]
    } else {
        removeAtPath(record[head], rest)
    }
}
