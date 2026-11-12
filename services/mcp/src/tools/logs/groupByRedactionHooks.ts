import { isCredentialName, redactCredentials, REDACTED_VALUE } from '@/lib/credential-redaction'
import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

interface GroupByParams {
    query?: {
        groupBy?: string
        groupBys?: { key: string }[]
    }
}

// Grouping by session is a documented use of logs-group-by, and PostHog session IDs join logs to replays.
const SESSION_ID_KEYS = new Set(['sessionid', 'session_id', '$session_id'])

function dimensionKeys(params: GroupByParams): string[] {
    const query = params.query
    if (query?.groupBys?.length) {
        return query.groupBys.map((dimension) => dimension.key)
    }
    return query?.groupBy ? [query.groupBy] : []
}

// Grouped values come back by position in `values`, so the name-based rule in redactCredentials never sees the key.
function afterResponse(_context: Context, params: GroupByParams, result: unknown): unknown {
    const masked = dimensionKeys(params).map((key) => !SESSION_ID_KEYS.has(key.toLowerCase()) && isCredentialName(key))
    if (masked.some(Boolean) && isRecord(result) && Array.isArray(result.groups)) {
        result = {
            ...result,
            groups: result.groups.map((group) => {
                if (!isRecord(group) || !Array.isArray(group.values)) {
                    return group
                }
                return {
                    ...group,
                    values: group.values.map((value, index) => (masked[index] ? REDACTED_VALUE : value)),
                }
            }),
        }
    }
    return redactCredentials(result)
}

export default { afterResponse } satisfies ToolHooks<GroupByParams>
