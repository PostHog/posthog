export interface ReplySuggestions {
    turnIndex: number
    replies: string[]
}

export function parseReplySuggestionsParams(params: unknown): ReplySuggestions | null {
    if (!params || typeof params !== 'object') {
        return null
    }
    const { turnIndex, suggestions } = params as Record<string, unknown>
    if (typeof turnIndex !== 'number' || !Array.isArray(suggestions)) {
        return null
    }
    const replies = suggestions
        .map((suggestion) => (suggestion as Record<string, unknown> | null)?.reply)
        .filter((reply): reply is string => typeof reply === 'string' && !!reply.trim())
    return replies.length ? { turnIndex, replies } : null
}
