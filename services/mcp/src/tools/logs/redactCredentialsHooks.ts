import {
    isCredentialName,
    isLogCredentialName,
    REDACTED_VALUE,
    redactCredentials,
    redactCredentialsInText,
} from '@/lib/credential-redaction'
import { assignKey, isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

// A `{ key, value }` pair names its attribute in `key`, so the pair's name decides whether `value` is a credential.
// The generic pass would treat the field called `key` as the credential instead.
function redactLogResponse(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(redactLogResponse)
    }
    if (!isRecord(value)) {
        return redactCredentials(value)
    }
    const pairName = typeof value.key === 'string' && 'value' in value ? value.key : null
    const redacted: Record<string, unknown> = {}
    for (const [field, entry] of Object.entries(value)) {
        let next: unknown
        if (pairName !== null && field === 'key') {
            next = redactCredentialsInText(pairName)
        } else if (pairName !== null && field === 'value') {
            next = isCredentialName(pairName, isLogCredentialName) ? REDACTED_VALUE : redactLogResponse(entry)
        } else {
            next = isCredentialName(field, isLogCredentialName) ? REDACTED_VALUE : redactLogResponse(entry)
        }
        assignKey(redacted, redactCredentialsInText(field), next)
    }
    return redacted
}

// Log bodies and attribute values are application text, so they can carry credentials the field filters cannot reach.
function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    return redactLogResponse(result)
}

export default { afterResponse } satisfies ToolHooks<unknown>
