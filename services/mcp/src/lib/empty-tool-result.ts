const PRIMARY_RESULT_KEYS: Record<string, string> = {
    'apm-service-health': 'services',
    'logs-context': 'timeline',
    'logs-group-by': 'groups',
}

// `apm-trace-get` returns a found trace as a summary, with no rows.
function summarizesSpans(result: Record<string, unknown>): boolean {
    const summary = result.summary
    return (
        typeof summary === 'object' && summary !== null && Number((summary as { span_count?: unknown }).span_count) > 0
    )
}

/**
 * Empty means "zero rows", in the two shapes the registered tools return:
 * a bare array, or the standardized `{ results: [...] }` envelope produced by
 * `withPostHogUrl` / `pickResponseFields` / the query-wrapper factory. Any
 * other shape is treated as non-empty, so this never has to guess.
 */
export function isEmptyToolResult(handlerResult: unknown, toolName?: string): boolean {
    if (Array.isArray(handlerResult)) {
        return handlerResult.length === 0
    }
    if (typeof handlerResult === 'object' && handlerResult !== null) {
        const key = (toolName && PRIMARY_RESULT_KEYS[toolName]) || 'results'
        const result = handlerResult as Record<string, unknown>
        const rows = result[key]
        return Array.isArray(rows) && rows.length === 0 && !summarizesSpans(result)
    }
    return false
}
