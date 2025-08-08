export interface SearchMatch {
    startIndex: number
    length: number
}

/**
 * Find all occurrences of a search query in a text string (case-insensitive)
 */
export function findSearchMatches(text: string, searchQuery: string): SearchMatch[] {
    if (!searchQuery.trim()) {
        return []
    }

    const query = searchQuery.toLowerCase().trim()
    const lowerText = text.toLowerCase()
    const matches: SearchMatch[] = []

    let searchIndex = 0
    while (searchIndex < lowerText.length) {
        const foundIndex = lowerText.indexOf(query, searchIndex)
        if (foundIndex === -1) {
            break
        }

        matches.push({
            startIndex: foundIndex,
            length: query.length,
        })

        searchIndex = foundIndex + query.length
    }

    return matches
}

/**
 * Check if a text contains a search query (case-insensitive)
 */
export function containsSearchQuery(text: string, searchQuery: string): boolean {
    if (!searchQuery.trim()) {
        return false
    }

    return text.toLowerCase().includes(searchQuery.toLowerCase().trim())
}

/**
 * Check if an LLM event matches a search query
 */
export function eventMatchesSearch(event: { properties: Record<string, any>; event?: string }, query: string): boolean {
    if (!query.trim()) {
        return true
    }

    const lowerQuery = query.toLowerCase().trim()

    // Search in event title
    const title = event.properties.$ai_span_name || event.event || ''
    if (title.toLowerCase().includes(lowerQuery)) {
        return true
    }

    // Search in model name
    const model = event.properties.$ai_model || ''
    if (model.toLowerCase().includes(lowerQuery)) {
        return true
    }

    // Search in provider
    const provider = event.properties.$ai_provider || ''
    if (provider.toLowerCase().includes(lowerQuery)) {
        return true
    }

    // Search in tools
    if (event.properties.$ai_tools) {
        const tools = JSON.stringify(event.properties.$ai_tools).toLowerCase()
        if (tools.includes(lowerQuery)) {
            return true
        }
    }

    // Search in input content
    const input = JSON.stringify(event.properties.$ai_input || event.properties.$ai_input_state || '').toLowerCase()
    if (input.includes(lowerQuery)) {
        return true
    }

    // Search in output content
    const output = JSON.stringify(
        event.properties.$ai_output || event.properties.$ai_output_choices || event.properties.$ai_output_state || ''
    ).toLowerCase()
    if (output.includes(lowerQuery)) {
        return true
    }

    // Search in error messages
    if (event.properties.$ai_error) {
        const error = JSON.stringify(event.properties.$ai_error).toLowerCase()
        if (error.includes(lowerQuery)) {
            return true
        }
    }

    return false
}
