import { assignKey, isRecord } from '@/lib/plain-object'
import redactCredentialsHooks from '@/tools/logs/redactCredentialsHooks'
import type { ToolHooks } from '@/tools/tool-hooks'
import { omitResponseFields } from '@/tools/tool-utils'
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
function afterResponse(context: Context, params: unknown, result: unknown): unknown {
    const redacted = redactCredentialsHooks.afterResponse(context, params, result)
    return groupResourceAttributes(
        omitResponseFields(redacted, [
            'results.*.observed_timestamp',
            'results.*.severity_number',
            'results.*.level',
            'results.*.live_logs_checkpoint',
        ])
    )
}

export default { afterResponse } satisfies ToolHooks<unknown>
