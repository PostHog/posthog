import {
    isCredentialName,
    isLogCredentialName,
    REDACTED_VALUE,
    redactCredentials,
    redactCredentialsInText,
} from '@/lib/credential-redaction'
import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

// logs-context returns attributes as `{ key, value }` pairs, where `key` names the attribute. The generic pass would
// treat the field called `key` as the credential, so these pairs are classified by their `key` instead.
function redactAttributePair(pair: unknown): unknown {
    if (!isRecord(pair) || typeof pair.key !== 'string') {
        return redactCredentials(pair)
    }
    const { key, value, ...rest } = pair
    return {
        ...(redactCredentials(rest) as Record<string, unknown>),
        key: redactCredentialsInText(key),
        value: isCredentialName(key, isLogCredentialName) ? REDACTED_VALUE : redactCredentials(value),
    }
}

function redactNextCall(call: unknown): unknown {
    const redacted = redactCredentials(call)
    const anchor = isRecord(call) && isRecord(call.query) && isRecord(call.query.anchor) ? call.query.anchor : null
    if (anchor === null || !('attribute' in anchor) || !isRecord(redacted) || !isRecord(redacted.query)) {
        return redacted
    }
    const redactedAnchor = redacted.query.anchor
    if (isRecord(redactedAnchor)) {
        redactedAnchor.attribute = redactAttributePair(anchor.attribute)
    }
    return redacted
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
            ? correlation_keys.map(redactAttributePair)
            : redactCredentials(correlation_keys)
    }
    if (next !== undefined) {
        redacted.next = Array.isArray(next) ? next.map(redactNextCall) : redactCredentials(next)
    }
    return redacted
}

export default { afterResponse } satisfies ToolHooks<unknown>
