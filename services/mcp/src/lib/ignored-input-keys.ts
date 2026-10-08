import type { z } from 'zod'

import { isToolCallPayload } from '@/lib/build-tool-result'
import { readParamAliases, reshapesInputBeyondAliases } from '@/tools/cast-helpers'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, POSTHOG_INFORMATIONAL_RESPONSE_KEY } from '@/tools/types'

const MAX_IGNORED_KEYS = 20
const MAX_KEY_LENGTH = 100
// Bound the walk so a deeply nested or very wide input stays cheap to diff.
const MAX_DEPTH = 12
const MAX_COLLECTED_KEYS = 100
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/g

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function collectIgnoredKeys(
    sent: unknown,
    kept: unknown,
    path: string,
    topLevelAliases: ReadonlySet<string>,
    into: string[],
    depth = 0
): void {
    if (depth > MAX_DEPTH || into.length >= MAX_COLLECTED_KEYS) {
        return
    }
    if (Array.isArray(sent) && Array.isArray(kept)) {
        sent.forEach((item, index) => {
            collectIgnoredKeys(
                item,
                kept[index],
                path ? `${path}.${index}` : String(index),
                topLevelAliases,
                into,
                depth + 1
            )
        })
        return
    }
    if (!isPlainObject(sent) || !isPlainObject(kept)) {
        return
    }
    for (const [key, value] of Object.entries(sent)) {
        if (value === undefined) {
            continue
        }
        const isTopLevel = path === ''
        const keyPath = isTopLevel ? key : `${path}.${key}`
        if (!Object.prototype.hasOwnProperty.call(kept, key)) {
            // The schema folds an alias into its canonical key, so it is not ignored.
            if (!(isTopLevel && topLevelAliases.has(key)) && into.length < MAX_COLLECTED_KEYS) {
                into.push(keyPath)
            }
            continue
        }
        collectIgnoredKeys(value, kept[key], keyPath, topLevelAliases, into, depth + 1)
    }
}

/**
 * Dotted paths of the sent keys that the validated arguments no longer contain.
 * Zod strips unknown keys without an error, so a misnamed field would otherwise look like a successful call.
 * Transforms that rename keys below the root are not detected.
 */
export function findIgnoredInputKeys(sent: unknown, parsed: unknown, schema: z.ZodType): string[] {
    if (reshapesInputBeyondAliases(schema)) {
        return []
    }
    const aliases = new Set(Object.values(readParamAliases(schema) ?? {}).flat())
    const ignored: string[] = []
    collectIgnoredKeys(sent, parsed, '', aliases, ignored)
    return ignored
}

function ignoredKeysNotice(ignoredKeys: string[], omitted: number): string {
    const more = omitted > 0 ? ` (and ${omitted} more)` : ''
    // JSON-encode each key so a caller-chosen name stays inside quotes and cannot read as an instruction.
    return `Ignored input keys: ${ignoredKeys.map((key) => JSON.stringify(key)).join(', ')}${more}. These keys are not part of the tool's input schema, so the tool did not use them.`
}

// The notice also goes into the formatted text override, because the agent sees that text instead of the object.
export function withIgnoredInputKeys(result: unknown, ignoredKeys: string[]): unknown {
    if (ignoredKeys.length === 0 || result === null || result === undefined) {
        return result
    }
    // Key names come from the caller. Mask control characters so they cannot fake lines in a server message.
    const keys = ignoredKeys
        .slice(0, MAX_IGNORED_KEYS)
        .map((key) => key.slice(0, MAX_KEY_LENGTH).replace(CONTROL_CHARACTERS, '?'))
    const omitted = ignoredKeys.length - keys.length
    const notice = ignoredKeysNotice(keys, omitted)

    if (typeof result === 'string') {
        return `${result}\n\n${notice}`
    }
    if (typeof result !== 'object' || isToolCallPayload(result)) {
        return result
    }

    // The marker properties live on the original value, not on the array wrapper.
    const markers = result as Record<string, unknown>
    const source = Array.isArray(result) ? { results: result } : markers
    const wrapped: Record<string, unknown> = { ...source, _ignoredKeys: keys, _ignoredKeysNote: notice }

    // Non-enumerable keys do not survive the spread above.
    const formatted = markers[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]
    if (typeof formatted === 'string') {
        Object.defineProperty(wrapped, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, {
            value: `${formatted}\n\n${notice}`,
            enumerable: false,
        })
    }
    if (markers[POSTHOG_INFORMATIONAL_RESPONSE_KEY] === true) {
        Object.defineProperty(wrapped, POSTHOG_INFORMATIONAL_RESPONSE_KEY, { value: true, enumerable: false })
    }
    return wrapped
}
