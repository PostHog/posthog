import type { z } from 'zod'

import { isToolCallPayload } from '@/lib/build-tool-result'
import { readParamAliases, reshapesInputBeyondAliases } from '@/tools/cast-helpers'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, POSTHOG_INFORMATIONAL_RESPONSE_KEY } from '@/tools/types'

const MAX_IGNORED_KEYS = 20
const MAX_KEY_LENGTH = 100
// Bounds on the walk, so a deeply nested or very wide input cannot make the diff expensive.
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
            // The schema folds an alias into its canonical key on purpose, so it is not an ignored key.
            if (!(isTopLevel && topLevelAliases.has(key)) && into.length < MAX_COLLECTED_KEYS) {
                into.push(keyPath)
            }
            continue
        }
        collectIgnoredKeys(value, kept[key], keyPath, topLevelAliases, into, depth + 1)
    }
}

/**
 * Dotted paths of the keys the caller sent that the validated arguments no longer contain.
 * Zod object schemas strip unknown keys without an error, so a misnamed field would otherwise
 * look like a successful call. Declared aliases are excluded because the schema folds them. A schema that reshapes its
 * input in other ways reports nothing, because the diff cannot tell consumed keys from dropped ones.
 * Transforms that rename keys below the root are not detected, so a nested schema must not do that.
 * Arrays of objects are compared index by index.
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
    // Each key is JSON-encoded so a caller-chosen name stays inside quotes and cannot read as an instruction.
    return `Ignored input keys: ${ignoredKeys.map((key) => JSON.stringify(key)).join(', ')}${more}. These keys are not part of the tool's input schema, so the tool did not use them.`
}

/**
 * Tells the calling agent which input keys the tool ignored. Returns the result unchanged when
 * nothing was ignored. A string result gets the notice appended. An object result gets
 * `_ignoredKeys` and `_ignoredKeysNote`, and a raw array is wrapped as `{ results, ... }`
 * like `withAgentNote`. The notice is also appended to the formatted text override, because
 * that text replaces the object for the agent. A tool-call payload passes through untouched.
 */
export function withIgnoredInputKeys(result: unknown, ignoredKeys: string[]): unknown {
    if (ignoredKeys.length === 0 || result === null || result === undefined) {
        return result
    }
    // Key names come from the caller, so control characters such as newlines are masked before
    // they reach a message written in the server's voice.
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

    // A raw array is wrapped like `withAgentNote` does. The markers sit on the original value,
    // not on the wrapper.
    const markers = result as Record<string, unknown>
    const source = Array.isArray(result) ? { results: result } : markers
    const wrapped: Record<string, unknown> = { ...source, _ignoredKeys: keys, _ignoredKeysNote: notice }

    // Non-enumerable keys do not survive the spread above, so copy them across by hand.
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
