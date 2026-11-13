import { isRecord } from '@/lib/plain-object'
import redactCredentialsHooks from '@/tools/logs/redactCredentialsHooks'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

export const MAX_BODY_LENGTH = 2000

// The logs UI uses these fields. For an agent they repeat `severity_text` and `timestamp`, or carry internal state.
const REDUNDANT_FIELDS = new Set([
    'observed_timestamp',
    'severity_number',
    'level',
    'resource_fingerprint',
    'live_logs_checkpoint',
])
const ZERO_ID = /^0+$/

function isEmpty(key: string, value: unknown): boolean {
    if (key === 'trace_id' || key === 'span_id') {
        return typeof value === 'string' && ZERO_ID.test(value)
    }
    if (key === 'attributes' || key === 'resource_attributes') {
        return isRecord(value) && Object.keys(value).length === 0
    }
    return key === 'event_name' && value === ''
}

function compactRow(row: unknown): unknown {
    if (!isRecord(row)) {
        return row
    }
    const compact: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(row)) {
        if (REDUNDANT_FIELDS.has(key) || isEmpty(key, value)) {
            continue
        }
        compact[key] =
            key === 'body' && typeof value === 'string' && value.length > MAX_BODY_LENGTH
                ? `${value.slice(0, MAX_BODY_LENGTH)}…[cut ${value.length - MAX_BODY_LENGTH} chars]`
                : value
    }
    return compact
}

// Redaction runs before the body is cut, because a cut through a credential leaves a fragment the redaction rules cannot match.
function afterResponse(context: Context, params: unknown, result: unknown): unknown {
    const redacted = redactCredentialsHooks.afterResponse(context, params, result)
    if (!isRecord(redacted) || !Array.isArray(redacted.results)) {
        return redacted
    }
    return { ...redacted, results: redacted.results.map(compactRow) }
}

export default { afterResponse } satisfies ToolHooks<unknown>
