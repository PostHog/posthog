export interface SearchMatch {
    startIndex: number
    length: number
}

export interface SearchOccurrence {
    type: 'sidebar' | 'message'
    eventId?: string // For both sidebar and message items
    messageIndex?: number // For messages
    messageType?: 'input' | 'output' // For messages
    field: string // 'title' | 'model' | 'provider' | 'role' | 'content' | 'error' | 'tools' | 'additionalKwargs'
    startIndex: number // Position within the field
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
 * Recursively extract all text content from an object, ignoring structure
 */
export function extractAllText(obj: unknown): string {
    if (typeof obj === 'string') {
        return obj
    }
    if (typeof obj === 'number' || typeof obj === 'boolean') {
        return String(obj)
    }
    if (!obj || typeof obj !== 'object') {
        return ''
    }

    const texts: string[] = []
    for (const value of Object.values(obj)) {
        const extracted = extractAllText(value)
        if (extracted) {
            texts.push(extracted)
        }
    }
    return texts.join(' ')
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
    const inputText = extractAllText(event.properties.$ai_input || event.properties.$ai_input_state).toLowerCase()
    if (input.includes(lowerQuery) || inputText.includes(lowerQuery)) {
        return true
    }

    // Search in output content
    const output = JSON.stringify(
        event.properties.$ai_output || event.properties.$ai_output_choices || event.properties.$ai_output_state || ''
    ).toLowerCase()
    const outputText = extractAllText(
        event.properties.$ai_output || event.properties.$ai_output_choices || event.properties.$ai_output_state
    ).toLowerCase()
    if (output.includes(lowerQuery) || outputText.includes(lowerQuery)) {
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

/**
 * Find all search occurrences in a text and create SearchOccurrence objects
 */
export function findSearchOccurrences(
    text: string,
    query: string,
    field: string,
    meta: Partial<SearchOccurrence>
): SearchOccurrence[] {
    const matches = findSearchMatches(text, query)
    return matches.map((match) => ({
        type: (meta.type || 'sidebar') as 'sidebar' | 'message',
        field,
        startIndex: match.startIndex,
        ...meta,
    }))
}

/**
 * Find search occurrences in trace-level fields
 */
export function findTraceOccurrences(
    trace: { id: string; traceName?: string } | null | undefined,
    query: string
): SearchOccurrence[] {
    if (!trace || !query.trim()) {
        return []
    }

    const occurrences: SearchOccurrence[] = []
    const traceTitle = trace.traceName || ''

    if (traceTitle) {
        occurrences.push(
            ...findSearchOccurrences(traceTitle, query, 'title', {
                type: 'sidebar',
                eventId: trace.id,
            })
        )
    }

    return occurrences
}

/**
 * Find search occurrences in sidebar event fields (title, model, provider)
 */
export function findSidebarOccurrences(
    events: Array<{ id: string; event?: string; properties: Record<string, any> }>,
    query: string
): SearchOccurrence[] {
    if (!query.trim()) {
        return []
    }

    const occurrences: SearchOccurrence[] = []

    events.forEach((event) => {
        // Event title (only from span name, not event.event)
        const title = event.properties.$ai_span_name || ''
        if (title) {
            occurrences.push(
                ...findSearchOccurrences(title, query, 'title', {
                    type: 'sidebar',
                    eventId: event.id,
                })
            )
        }

        // Model and provider (displayed together in the UI)
        if (event.event === '$ai_generation' && event.properties.$ai_span_name) {
            let modelText = event.properties.$ai_model || ''
            if (event.properties.$ai_provider) {
                modelText = `${modelText} (${event.properties.$ai_provider})`
            }
            // Use 'model' field for the combined model + provider string
            if (modelText) {
                occurrences.push(
                    ...findSearchOccurrences(modelText, query, 'model', {
                        type: 'sidebar',
                        eventId: event.id,
                    })
                )
            }
        }
    })

    return occurrences
}

/**
 * Find search occurrences in message content and related fields
 */
export function findMessageOccurrences(
    events: Array<{ id: string; event?: string; properties: Record<string, any> }>,
    query: string,
    normalizeMessages: (input: any, defaultRole: string, tools?: any) => any[]
): SearchOccurrence[] {
    if (!query.trim()) {
        return []
    }

    const occurrences: SearchOccurrence[] = []

    events.forEach((event) => {
        // Tools in input (displayed as "available tools")
        if (event.event === '$ai_generation' && event.properties.$ai_tools) {
            const toolsStr = JSON.stringify(event.properties.$ai_tools)
            occurrences.push(
                ...findSearchOccurrences(toolsStr, query, 'tools', {
                    type: 'message',
                    eventId: event.id,
                    messageType: 'input',
                })
            )
        }

        // Input messages
        if (event.event === '$ai_generation') {
            const normalizedInput = normalizeMessages(event.properties.$ai_input, 'user', event.properties.$ai_tools)
            normalizedInput.forEach((msg, msgIndex) => {
                // Content
                const content = typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content)
                occurrences.push(
                    ...findSearchOccurrences(content, query, 'content', {
                        type: 'message',
                        eventId: event.id,
                        messageIndex: msgIndex,
                        messageType: 'input',
                    })
                )

                // Additional kwargs
                const { role: _r, content: _c, tools: _t, ...additionalKwargs } = msg
                if (Object.keys(additionalKwargs).length > 0) {
                    const additionalStr = JSON.stringify(additionalKwargs)
                    occurrences.push(
                        ...findSearchOccurrences(additionalStr, query, 'additionalKwargs', {
                            type: 'message',
                            eventId: event.id,
                            messageIndex: msgIndex,
                            messageType: 'input',
                        })
                    )
                }
            })
        } else {
            // Fallback for non-generation events
            const inputMessages = event.properties.$ai_input
            if (Array.isArray(inputMessages)) {
                inputMessages.forEach((msg, msgIndex) => {
                    const content = typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content)
                    occurrences.push(
                        ...findSearchOccurrences(content, query, 'content', {
                            type: 'message',
                            eventId: event.id,
                            messageIndex: msgIndex,
                            messageType: 'input',
                        })
                    )
                })
            }
        }

        // Output messages
        if (event.event === '$ai_generation') {
            const outputToNormalize = event.properties.$ai_output_choices ?? event.properties.$ai_output
            const normalizedOutput = normalizeMessages(outputToNormalize, 'assistant')

            normalizedOutput.forEach((msg, msgIndex) => {
                // Content
                const content = typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content)
                occurrences.push(
                    ...findSearchOccurrences(content, query, 'content', {
                        type: 'message',
                        eventId: event.id,
                        messageIndex: msgIndex,
                        messageType: 'output',
                    })
                )

                // Additional kwargs
                const { role: _role, content: _content, ...additionalKwargs } = msg
                if (Object.keys(additionalKwargs).length > 0) {
                    const additionalStr = JSON.stringify(additionalKwargs)
                    occurrences.push(
                        ...findSearchOccurrences(additionalStr, query, 'additionalKwargs', {
                            type: 'message',
                            eventId: event.id,
                            messageIndex: msgIndex,
                            messageType: 'output',
                        })
                    )
                }
            })
        } else {
            // Fallback for non-generation events
            const outputMessages = event.properties.$ai_output_choices || event.properties.$ai_output
            if (Array.isArray(outputMessages)) {
                outputMessages.forEach((msg, msgIndex) => {
                    const content = typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content)
                    occurrences.push(
                        ...findSearchOccurrences(content, query, 'content', {
                            type: 'message',
                            eventId: event.id,
                            messageIndex: msgIndex,
                            messageType: 'output',
                        })
                    )

                    const { role: _roleMsg, content: _contentMsg, ...additionalKwargs } = msg
                    if (Object.keys(additionalKwargs).length > 0) {
                        const additionalStr = JSON.stringify(additionalKwargs)
                        occurrences.push(
                            ...findSearchOccurrences(additionalStr, query, 'additionalKwargs', {
                                type: 'message',
                                eventId: event.id,
                                messageIndex: msgIndex,
                                messageType: 'output',
                            })
                        )
                    }
                })
            }
        }

        // Error messages
        if (event.properties.$ai_error) {
            const error = JSON.stringify(event.properties.$ai_error)
            occurrences.push(
                ...findSearchOccurrences(error, query, 'error', {
                    type: 'message',
                    eventId: event.id,
                })
            )
        }
    })

    return occurrences
}
