/**
 * Format trace with hierarchical tree view of spans and generations
 * Avoids duplication by showing a tree structure instead of full content for each node
 */
import { formatEventTextRepr } from '../textFormatter'

interface TraceTreeNode {
    event: any
    children?: TraceTreeNode[]
}

/**
 * Truncate content with middle ellipsis for long text
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

    const encodedMiddle = btoa(encodeURIComponent(middlePart))
    const marker = `<<<TRUNCATED|${encodedMiddle}|${truncatedChars}>>>`

    return {
        lines: [firstPart, '', marker, '', lastPart],
        truncated: true,
    }
}

/**
 * Format a state object for display
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
        if (typeof state === 'string') {
            const { lines: contentLines } = truncateContent(state)
            lines.push(...contentLines)
            return lines
        }

        if (typeof state === 'object') {
            const jsonStr = JSON.stringify(state, null, 2)
            const { lines: contentLines } = truncateContent(jsonStr)
            lines.push(...contentLines)
            return lines
        }

        lines.push(String(state))
        return lines
    } catch {
        // Safe fallback if JSON.stringify fails (circular refs, etc.)
        lines.push(`[UNABLE_TO_PARSE: ${typeof state}]`)
        return lines
    }
}

/**
 * Format latency to 2 decimal places
 */
function formatLatency(latency: number): string {
    return `${latency.toFixed(2)}s`
}

/**
 * Format cost in USD
 */
function formatCost(cost: number): string {
    return `$${cost.toFixed(4)}`
}

/**
 * Get a brief summary of an event for tree display
 */
function getEventSummary(event: any): string {
    const props = event.properties
    const eventType = event.event

    if (eventType === '$ai_generation') {
        const spanName = props.$ai_span_name || props.$ai_model || 'generation'
        const latency = props.$ai_latency ? formatLatency(props.$ai_latency) : ''
        const cost = props.$ai_total_cost_usd ? formatCost(props.$ai_total_cost_usd) : ''
        const model = props.$ai_model || 'unknown'
        const error = props.$ai_is_error || props.$ai_error ? 'ERROR' : ''
        const parts = [latency, cost, model, error].filter(Boolean)
        return `${spanName}${parts.length > 0 ? ` (${parts.join(', ')})` : ''}`
    }

    if (eventType === '$ai_span') {
        const spanName = props.$ai_span_name || 'span'
        const latency = props.$ai_latency ? formatLatency(props.$ai_latency) : ''
        const error = props.$ai_is_error ? 'ERROR' : ''
        const parts = [latency, error].filter(Boolean)
        return `${spanName}${parts.length > 0 ? ` (${parts.join(', ')})` : ''}`
    }

    return eventType
}

/**
 * Render tree structure with ASCII art
 * Embeds event IDs in a special format for click handling: <<<EVENT_LINK|eventId|displayText>>>
 * For generations and spans, also embeds expandable content: <<<GEN_EXPANDABLE|eventId|summary|encodedContent>>>
 */
function renderTree(nodes: TraceTreeNode[], prefix = '', isLast = true, depth = 0): string[] {
    const lines: string[] = []
    const maxDepth = 10 // Prevent infinite nesting

    if (depth > maxDepth) {
        lines.push(`${prefix}  [... max depth reached]`)
        return lines
    }

    for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i]
        const isLastNode = i === nodes.length - 1
        const currentPrefix = isLast ? '└─ ' : '├─ '
        const childPrefix = isLast ? '   ' : '│  '

        const summary = getEventSummary(node.event)
        const eventType = node.event.event

        // Format the node line with event type prefix
        let nodePrefix = ''
        if (eventType === '$ai_generation') {
            nodePrefix = '[GEN]'

            // Create expandable generation content
            const eventId = node.event.id
            const genContent = formatEventTextRepr(node.event)
            const encodedContent = btoa(encodeURIComponent(genContent))

            // Include summary in display text
            const displayText = `${nodePrefix} ${summary}`

            // Create expandable marker with encoded content
            const expandableMarker = `<<<GEN_EXPANDABLE|${eventId}|${displayText}|${encodedContent}>>>`

            lines.push(`${prefix}${currentPrefix}${expandableMarker}`)
        } else if (eventType === '$ai_span') {
            nodePrefix = '[SPAN]'

            // Create expandable span content
            const eventId = node.event.id
            const spanContent = formatEventTextRepr(node.event)
            const encodedContent = btoa(encodeURIComponent(spanContent))

            // Include summary in display text
            const displayText = `${nodePrefix} ${summary}`

            // Create expandable marker with encoded content
            const expandableMarker = `<<<GEN_EXPANDABLE|${eventId}|${displayText}|${encodedContent}>>>`

            lines.push(`${prefix}${currentPrefix}${expandableMarker}`)
        } else {
            // For other events, use regular event link
            const eventId = node.event.id
            const clickablePrefix = `<<<EVENT_LINK|${eventId}|${nodePrefix}>>>`
            lines.push(`${prefix}${currentPrefix}${clickablePrefix} ${summary}`)
        }

        // Recursively render children
        if (node.children && node.children.length > 0) {
            const childLines = renderTree(node.children, prefix + childPrefix, isLastNode, depth + 1)
            lines.push(...childLines)
        }
    }

    return lines
}

/**
 * Generate complete text representation of a trace
 */
export function formatTraceTextRepr(trace: any, tree: TraceTreeNode[]): string {
    const lines: string[] = []
    const props = trace.properties || {}

    // Trace header
    const traceName = props.$ai_span_name || 'TRACE'
    lines.push(traceName.toUpperCase())
    lines.push('='.repeat(80))

    // Trace-level metadata section
    const metadata: string[] = []
    const traceId = props.$ai_trace_id || trace.trace_id
    if (traceId) {
        metadata.push(`Trace ID: ${traceId}`)
    }

    if (props.$ai_session_id) {
        metadata.push(`Session ID: ${props.$ai_session_id}`)
    }

    if (props.$ai_latency !== undefined && props.$ai_latency !== null) {
        metadata.push(`Total Latency: ${props.$ai_latency}s`)
    }

    // Add aggregated metrics from trace if available
    if (trace.total_cost !== undefined && trace.total_cost !== null && trace.total_cost > 0) {
        metadata.push(`Total Cost: $${trace.total_cost.toFixed(4)}`)
    }

    if (trace.total_tokens !== undefined && trace.total_tokens !== null && trace.total_tokens > 0) {
        metadata.push(`Total Tokens: ${trace.total_tokens}`)
    }

    if (metadata.length > 0) {
        lines.push('')
        lines.push(...metadata)
    }

    // Error information (if at trace level)
    if (props.$ai_error) {
        lines.push('')
        lines.push('-'.repeat(80))
        lines.push('')
        lines.push('TRACE ERROR:')
        lines.push('')
        if (typeof props.$ai_error === 'string') {
            lines.push(props.$ai_error)
        } else {
            lines.push(JSON.stringify(props.$ai_error, null, 2))
        }
    }

    // Trace-level input state
    const inputLines = formatState(props.$ai_input_state, 'TRACE INPUT')
    if (inputLines.length > 0) {
        lines.push('')
        lines.push('-'.repeat(80))
        lines.push(...inputLines)
    }

    // Trace-level output state
    const outputLines = formatState(props.$ai_output_state, 'TRACE OUTPUT')
    if (outputLines.length > 0) {
        lines.push('')
        lines.push('-'.repeat(80))
        lines.push(...outputLines)
    }

    // Tree structure
    if (tree && tree.length > 0) {
        lines.push('')
        lines.push('-'.repeat(80))
        lines.push('')
        lines.push('TRACE HIERARCHY:')
        lines.push('')
        lines.push(...renderTree(tree))
    }

    return lines.join('\n')
}

/**
 * Generate text representation for a single event within a trace context
 * This is used when viewing a specific generation or span from the trace
 */
export function formatTraceEventTextRepr(event: any): string {
    // Reuse the existing formatters for individual events
    return formatEventTextRepr(event)
}
