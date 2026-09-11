/** Characters per token in the heuristic below, so a token budget converts to a character one. */
export const CHARS_PER_TOKEN = 4

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
    return Math.ceil(text.length / CHARS_PER_TOKEN)
}
