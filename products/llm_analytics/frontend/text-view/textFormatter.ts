/**
 * Main text formatter for $ai_generation events
 * Combines metadata, tools, input, and output into a readable text representation
 */
import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { formatInputMessages, formatOutputMessages } from './formatters/messageFormatter'
import { formatTools } from './formatters/toolFormatter'

/**
 * Generate complete text representation of a generation event
 * This is the main entry point for converting an event to text
 */
export function formatGenerationTextRepr(event: LLMTraceEvent): string {
    const lines: string[] = []
    const props = event.properties

    // Header
    lines.push('='.repeat(80))
    lines.push(`Event: ${event.event}`)
    lines.push(`ID: ${event.id}`)
    lines.push(`Time: ${event.createdAt}`)

    // Trace hierarchy - only show fields that have values
    if (props.$ai_trace_id) {
        lines.push(`Trace: ${props.$ai_trace_id}`)
    }
    if (props.$ai_session_id) {
        lines.push(`Session: ${props.$ai_session_id}`)
    }
    if (props.$ai_span_id) {
        lines.push(`Span: ${props.$ai_span_id}`)
    }
    if (props.$ai_parent_id) {
        lines.push(`Parent: ${props.$ai_parent_id}`)
    }
    // Tools (if available)
    const toolsLines = formatTools(props.$ai_tools)
    if (toolsLines.length > 0) {
        lines.push('')
        lines.push('-'.repeat(80))
        lines.push(...toolsLines)
    }

    // Input messages
    const inputLines = formatInputMessages(props.$ai_input)
    if (inputLines.length > 0) {
        lines.push('')
        lines.push('-'.repeat(80))
        lines.push(...inputLines)
    }

    // Output messages
    const outputLines = formatOutputMessages(props.$ai_output, props.$ai_output_choices)
    if (outputLines.length > 0) {
        lines.push('')
        lines.push('-'.repeat(80))
        lines.push(...outputLines)
    }

    // Footer
    lines.push('')
    lines.push('='.repeat(80))

    return lines.join('\n')
}
