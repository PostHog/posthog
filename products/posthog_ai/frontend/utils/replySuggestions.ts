export interface ReplySuggestion {
    label: string
    reply: string
}

export interface ReplySuggestions {
    turnIndex: number
    suggestions: ReplySuggestion[]
}

function parseReplySuggestion(raw: unknown): ReplySuggestion | null {
    if (!raw || typeof raw !== 'object') {
        return null
    }
    const { label, reply } = raw as Record<string, unknown>
    if (typeof reply !== 'string' || !reply.trim()) {
        return null
    }
    return { label: typeof label === 'string' && label.trim() ? label : reply, reply }
}

export function parseReplySuggestionsParams(params: unknown): ReplySuggestions | null {
    if (!params || typeof params !== 'object') {
        return null
    }
    const { turnIndex, suggestions } = params as Record<string, unknown>
    if (typeof turnIndex !== 'number' || !Array.isArray(suggestions)) {
        return null
    }
    const parsed = suggestions.map(parseReplySuggestion).filter((s): s is ReplySuggestion => s !== null)
    return parsed.length ? { turnIndex, suggestions: parsed } : null
}
