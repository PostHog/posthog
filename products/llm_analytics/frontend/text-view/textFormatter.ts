/**
 * Main text formatter for LLM trace events
 * Combines metadata, tools, input, and output into a readable text representation
 * Supports both $ai_generation and $ai_span events
 */
import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { formatInputMessages, formatOutputMessages } from './formatters/messageFormatter'
import { formatSpanTextRepr } from './formatters/spanFormatter'
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

/**
 * Generate complete text representation of any LLM event
 * Routes to the appropriate formatter based on event type
 */
export function formatEventTextRepr(event: LLMTraceEvent): string {
    if (event.event === '$ai_span') {
        return formatSpanTextRepr(event)
    }

    // Default to generation formatter for $ai_generation and other events
    return formatGenerationTextRepr(event)
}
