import { redactCredentials } from '@/lib/credential-redaction'
import { assignKey, isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

/** Every row from one pod repeats its resource attributes, which are most of a page's size. */
function groupResourceAttributes(result: unknown): unknown {
    if (!isRecord(result) || !Array.isArray(result.results)) {
        return result
    }
    const resources: Record<string, unknown> = {}
    const results = result.results.map((row: unknown) => {
        if (!isRecord(row) || typeof row.resource_fingerprint !== 'string' || !isRecord(row.resource_attributes)) {
            return row
        }
        const { resource_attributes: resourceAttributes, ...rest } = row
        if (!Object.prototype.hasOwnProperty.call(resources, row.resource_fingerprint)) {
            assignKey(resources, row.resource_fingerprint, resourceAttributes)
        }
        return rest
    })
    return Object.keys(resources).length ? { ...result, results, resources } : { ...result, results }
}

// Log bodies and attribute values are application text, so they can carry credentials the field filters cannot reach.
function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    return groupResourceAttributes(redactCredentials(result))
}

export default { afterResponse } satisfies ToolHooks<unknown>
