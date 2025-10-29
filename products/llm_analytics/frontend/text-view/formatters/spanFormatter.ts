/**
 * Format span events for text view
 * Spans represent units of work within an LLM trace
 */

/**
 * Truncate content with middle ellipsis for long text
 * Embeds full content in a special marker format for click-to-expand functionality
 */
function truncateContent(content: string, maxLength = 1000): { lines: string[]; truncated: boolean } {
    if (content.length <= maxLength) {
        return { lines: [content], truncated: false }
    }

    const half = Math.floor(maxLength / 2)
    const firstPart = content.slice(0, half)
    const lastPart = content.slice(-half)
    const truncatedChars = content.length - maxLength
    const middlePart = content.slice(half, -half)

    // Encode the middle part in a special marker format that we'll parse in the display component
    // Format: <<<TRUNCATED|base64content|charCount>>>
    const encodedMiddle = btoa(encodeURIComponent(middlePart))
    const marker = `<<<TRUNCATED|${encodedMiddle}|${truncatedChars}>>>`

    return {
        lines: [firstPart, '', marker, '', lastPart],
        truncated: true,
    }
}

/**
 * Format a state object (input or output) for display
 */
function formatState(state: any, label: string): string[] {
    if (!state) {
        return []
    }

    const lines: string[] = []
    lines.push('')
    lines.push(`${label}:`)
    lines.push('')

    try {
        // Handle string state
        if (typeof state === 'string') {
            const { lines: contentLines } = truncateContent(state)
            lines.push(...contentLines)
            return lines
        }

        // Handle object state
        if (typeof state === 'object') {
            const jsonStr = JSON.stringify(state, null, 2)
            const { lines: contentLines } = truncateContent(jsonStr)
            lines.push(...contentLines)
            return lines
        }

        // Fallback for other types
        lines.push(String(state))
        return lines
    } catch {
        // Safe fallback if JSON.stringify fails (circular refs, etc.)
        lines.push(`[UNABLE_TO_PARSE: ${typeof state}]`)
        return lines
    }
}

/**
 * Generate complete text representation of a span event
 */
export function formatSpanTextRepr(event: any): string {
    const lines: string[] = []
    const props = event.properties

    // Span name/title
    const spanName = props.$ai_span_name || 'Span'
    lines.push(spanName.toUpperCase())
    lines.push('='.repeat(80))

    // Error information
    if (props.$ai_error) {
        lines.push('-'.repeat(80))
        lines.push('')
        lines.push('ERROR:')
        lines.push('')
        if (typeof props.$ai_error === 'string') {
            lines.push(props.$ai_error)
        } else if (typeof props.$ai_error === 'object') {
            lines.push(JSON.stringify(props.$ai_error, null, 2))
        } else {
            lines.push(String(props.$ai_error))
        }
        lines.push('')
    }

    // Input state
    const inputLines = formatState(props.$ai_input_state, 'INPUT STATE')
    if (inputLines.length > 0) {
        if (lines.length > 0 && !lines[lines.length - 1].startsWith('-')) {
            lines.push('-'.repeat(80))
        }
        lines.push(...inputLines)
    }

    // Output state
    const outputLines = formatState(props.$ai_output_state, 'OUTPUT STATE')
    if (outputLines.length > 0) {
        if (lines.length > 0 && !lines[lines.length - 1].startsWith('-')) {
            lines.push('')
            lines.push('-'.repeat(80))
        }
        lines.push(...outputLines)
    }

    return lines.join('\n')
}
