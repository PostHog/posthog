/**
 * Main text formatter for $ai_generation events
 * Combines metadata, tools, input, and output into a readable text representation
 */
import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { formatInputMessages, formatOutputMessages } from './formatters/messageFormatter'
import { formatTools } from './formatters/toolFormatter'

const SEPARATOR = '-'.repeat(80)

/**
 * Generate complete text representation of a generation event
 * This is the main entry point for converting an event to text
 */
export function formatGenerationTextRepr(event: LLMTraceEvent): string {
    const lines: string[] = []
    const props = event.properties

    // Tools (if available)
    const toolsLines = formatTools(props.$ai_tools)
    if (toolsLines.length > 0) {
        lines.push(SEPARATOR)
        lines.push(...toolsLines)
    }

    // Input messages
    const inputLines = formatInputMessages(props.$ai_input)
    if (inputLines.length > 0) {
        if (lines.length > 0) {
            lines.push('')
        }
        lines.push(SEPARATOR)
        lines.push(...inputLines)
    }

    // Output messages
    const outputLines = formatOutputMessages(props.$ai_output, props.$ai_output_choices)
    if (outputLines.length > 0) {
        if (lines.length > 0) {
            lines.push('')
        }
        lines.push(SEPARATOR)
        lines.push(...outputLines)
    }

    return lines.join('\n')
}
