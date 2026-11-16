import { redactCredentials, redactKeyValuePair } from '@/lib/credential-redaction'
import { canonicalJson, isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

// Next calls carry `{ key, value }` pairs in a logs-context anchor attribute and in query-logs property filters.
function redactNextCall(call: unknown): unknown {
    const redacted = redactCredentials(call)
    const query = isRecord(call) && isRecord(call.query) ? call.query : null
    if (query === null || !isRecord(redacted) || !isRecord(redacted.query)) {
        return redacted
    }
    if (isRecord(query.anchor) && 'attribute' in query.anchor && isRecord(redacted.query.anchor)) {
        redacted.query.anchor.attribute = redactKeyValuePair(query.anchor.attribute)
    }
    if (Array.isArray(query.filterGroup)) {
        redacted.query.filterGroup = query.filterGroup.map((filter) => redactKeyValuePair(filter))
    }
    return redacted
}

function nextCallQuery(call: unknown): string {
    return canonicalJson(isRecord(call) ? call.query : undefined)
}

// A next call whose query arguments were redacted would search for the literal `[REDACTED]`, so it is dropped.
function redactNextCalls(next: unknown[]): unknown[] {
    return next.flatMap((call) => {
        const redacted = redactNextCall(call)
        return nextCallQuery(redacted) === nextCallQuery(call) ? [redacted] : []
    })
}

// Log bodies and attribute values are application text, so they can carry credentials the field filters cannot reach.
function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    if (!isRecord(result)) {
        return redactCredentials(result)
    }
    const { correlation_keys, next, ...rest } = result
    const redacted = redactCredentials(rest) as Record<string, unknown>
    if (correlation_keys !== undefined) {
        redacted.correlation_keys = Array.isArray(correlation_keys)
            ? correlation_keys.map((pair) => redactKeyValuePair(pair))
            : redactCredentials(correlation_keys)
    }
    if (next !== undefined) {
        redacted.next = Array.isArray(next) ? redactNextCalls(next) : redactCredentials(next)
    }
    return redacted
}

export default { afterResponse } satisfies ToolHooks<unknown>
