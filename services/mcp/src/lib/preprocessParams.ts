/**
 * Preprocess MCP tool arguments to handle clients that serialize nested objects
 * as JSON strings. Only coerces top-level string values that look like JSON
 * objects or arrays.
 */
export function preprocessParams(params: Record<string, unknown>): Record<string, unknown> {
    const result = { ...params }
    for (const [key, value] of Object.entries(result)) {
        if (typeof value === 'string') {
            const trimmed = value.trim()
            if (
                (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
                (trimmed.startsWith('[') && trimmed.endsWith(']'))
            ) {
                try {
                    result[key] = JSON.parse(trimmed)
                } catch {
                    // Keep original string if not valid JSON
                }
            }
        }
    }
    return result
}
