/**
 * Approximate token count for a tool call's input or output, using the
 * ~4-chars-per-token heuristic the MCP performance dashboard tracks. The server
 * does not capture LLM-observability spans, so token usage is estimated from the
 * serialized size of the value rather than read from a generation/trace payload.
 */
export function estimateTokens(value: unknown): number {
    if (value === undefined || value === null) {
        return 0
    }
    let text: string
    if (typeof value === 'string') {
        text = value
    } else {
        try {
            text = JSON.stringify(value) ?? ''
        } catch {
            // Non-serializable value (circular refs, BigInt, ...) — never break
            // the request for an analytics estimate.
            return 0
        }
    }
    return Math.ceil(text.length / 4)
}
