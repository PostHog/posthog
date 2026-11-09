const PRIMARY_RESULT_KEYS: Record<string, string> = {
    'apm-service-health': 'services',
    'logs-context': 'timeline',
    'logs-group-by': 'groups',
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
        const rows = (handlerResult as Record<string, unknown>)[key]
        return Array.isArray(rows) && rows.length === 0
    }
    return false
}
