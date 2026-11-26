import { isCredentialField, isSpanCredentialName, redactCredentials, REDACTED_VALUE } from '@/lib/credential-redaction'
import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

interface AttributeParams {
    key?: string
    query?: { breakdownKey?: string }
}

// Fields that hold the requested attribute's value in values-list (`id`, `name`) and breakdown (`value`) rows.
const VALUE_FIELDS = ['id', 'name', 'value']

function maskRow(row: unknown, key: string | undefined): unknown {
    if (!isRecord(row)) {
        return row
    }
    if (key !== undefined) {
        const masked = { ...row }
        for (const field of VALUE_FIELDS) {
            if (field in masked && isCredentialField(key, masked[field], isSpanCredentialName)) {
                masked[field] = REDACTED_VALUE
            }
        }
        return masked
    }
    // apm-attributes-list names the attribute in `name` and returns a sample value in `matchedValue`.
    if (
        typeof row.name === 'string' &&
        typeof row.matchedValue === 'string' &&
        isCredentialField(row.name, row.matchedValue, isSpanCredentialName)
    ) {
        return { ...row, matchedValue: REDACTED_VALUE }
    }
    return row
}

// These tools return attribute values under neutral fields, so the name-based rule in redactCredentials never sees
// the attribute key. The key comes from the request instead, or from each row for apm-attributes-list.
function afterResponse(_context: Context, params: unknown, result: unknown): unknown {
    const { key, query } = params as AttributeParams
    const attributeKey = key ?? query?.breakdownKey
    if (!isRecord(result)) {
        return redactCredentials(result, isSpanCredentialName)
    }
    const masked = { ...result }
    for (const field of ['results', 'compare']) {
        const rows = masked[field]
        if (Array.isArray(rows)) {
            masked[field] = rows.map((row) => maskRow(row, attributeKey))
        }
    }
    return redactCredentials(masked, isSpanCredentialName)
}

export default { afterResponse } satisfies ToolHooks<unknown>
