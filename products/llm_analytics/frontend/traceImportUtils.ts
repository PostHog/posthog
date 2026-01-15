import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EnrichedTraceTreeNode, TraceTreeNode, restoreTree } from './llmAnalyticsTraceDataLogic'
import { CompatMessage } from './types'
import { formatLLMUsage } from './utils'

export interface EventMetrics {
    latency?: number
    tokens?: {
        input: number
        output: number
    }
    cost?: number
}

export interface TokenUsage {
    input: number
    output: number
}

export interface MinimalTraceExport {
    trace_id: string
    name?: string
    timestamp: string
    total_cost?: number
    total_tokens: TokenUsage
    events: MinimalEventExport[]
}

export interface MinimalEventExport {
    type: 'generation' | 'span' | 'trace' | 'embedding'
    name: string
    model?: string
    provider?: string
    messages?: CompatMessage[]
    input?: unknown
    output?: unknown
    available_tools?: unknown[]
    error?: string | Record<string, unknown>
    metrics?: EventMetrics
    children?: MinimalEventExport[]
}

interface ParseResult {
    trace: LLMTrace
    enrichedTree: EnrichedTraceTreeNode[]
}

interface ValidationResult {
    valid: boolean
    error?: string
}

export function validateTraceExport(data: unknown): ValidationResult {
    if (!data || typeof data !== 'object') {
        return { valid: false, error: 'Invalid JSON structure: expected an object' }
    }

    const trace = data as Record<string, unknown>

    if (!trace.trace_id || typeof trace.trace_id !== 'string') {
        return { valid: false, error: 'Missing or invalid trace_id' }
    }

    if (!trace.timestamp || typeof trace.timestamp !== 'string') {
        return { valid: false, error: 'Missing or invalid timestamp' }
    }

    if (!trace.events || !Array.isArray(trace.events)) {
        return { valid: false, error: 'Missing or invalid events array' }
    }

    if (trace.events.length === 0) {
        return { valid: false, error: 'Events array is empty' }
    }

    return { valid: true }
}

let eventCounter = 0

function generateEventId(): string {
    return `preview-event-${++eventCounter}`
}

function convertEventToInternal(
    event: MinimalEventExport,
    traceId: string,
    parentId?: string
): { event: LLMTraceEvent; childEvents: LLMTraceEvent[] } {
    const eventId = generateEventId()
    const isGeneration = event.type === 'generation'
    const isEmbedding = event.type === 'embedding'
    const eventType = isGeneration ? '$ai_generation' : isEmbedding ? '$ai_embedding' : '$ai_span'

    const properties: Record<string, unknown> = {
        $ai_trace_id: traceId,
        $ai_span_name: event.name,
    }

    if (parentId) {
        properties.$ai_parent_id = parentId
    }

    if (isGeneration) {
        properties.$ai_generation_id = eventId

        if (event.model) {
            properties.$ai_model = event.model
        }

        if (event.provider) {
            properties.$ai_provider = event.provider
        }

        // Convert messages back to input/output format
        if (event.messages && event.messages.length > 0) {
            const inputMessages = event.messages.filter((m) => m.role !== 'assistant')
            const outputMessages = event.messages.filter((m) => m.role === 'assistant')

            if (inputMessages.length > 0) {
                properties.$ai_input = inputMessages
            }

            if (outputMessages.length > 0) {
                properties.$ai_output_choices = outputMessages
            }
        }

        if (event.available_tools) {
            properties.$ai_tools = event.available_tools
        }
    } else if (isEmbedding) {
        properties.$ai_embedding_id = eventId

        if (event.model) {
            properties.$ai_model = event.model
        }

        if (event.provider) {
            properties.$ai_provider = event.provider
        }

        if (event.input !== undefined) {
            properties.$ai_input = event.input
        }
    } else {
        properties.$ai_span_id = eventId

        if (event.input !== undefined) {
            properties.$ai_input_state = event.input
        }

        if (event.output !== undefined) {
            properties.$ai_output_state = event.output
        }
    }

    // Handle error information
    if (event.error) {
        properties.$ai_is_error = true
        if (typeof event.error === 'string' && event.error !== 'Error occurred (details not available)') {
            properties.$ai_error = event.error
        } else if (typeof event.error === 'object') {
            properties.$ai_error = event.error
        }
    }

    // Handle metrics
    if (event.metrics) {
        if (event.metrics.latency !== undefined) {
            properties.$ai_latency = event.metrics.latency
        }

        if (event.metrics.tokens) {
            properties.$ai_input_tokens = event.metrics.tokens.input
            properties.$ai_output_tokens = event.metrics.tokens.output
        }

        if (event.metrics.cost !== undefined) {
            properties.$ai_total_cost_usd = event.metrics.cost
        }
    }

    const internalEvent: LLMTraceEvent = {
        id: eventId,
        event: eventType,
        properties,
        createdAt: new Date().toISOString(),
    }

    // Process children recursively
    const allChildEvents: LLMTraceEvent[] = []

    if (event.children && event.children.length > 0) {
        for (const child of event.children) {
            const { event: childEvent, childEvents } = convertEventToInternal(child, traceId, eventId)
            allChildEvents.push(childEvent, ...childEvents)
        }
    }

    return { event: internalEvent, childEvents: allChildEvents }
}

function enrichNode(node: TraceTreeNode): EnrichedTraceTreeNode {
    const event = node.event

    return {
        ...node,
        children: node.children?.map(enrichNode),
        displayTotalCost: node.aggregation?.totalCost ?? event.properties.$ai_total_cost_usd ?? 0,
        displayLatency: node.aggregation?.totalLatency ?? event.properties.$ai_latency ?? 0,
        displayUsage: node.aggregation ? formatLLMUsage(node.aggregation) : formatLLMUsage(event),
    }
}

export function parseTraceExportJson(json: string): ParseResult {
    // Reset counter for each parse to ensure consistent IDs
    eventCounter = 0

    const data = JSON.parse(json) as MinimalTraceExport

    const validation = validateTraceExport(data)

    if (!validation.valid) {
        throw new Error(validation.error)
    }

    // Convert all events to internal format
    const allEvents: LLMTraceEvent[] = []

    for (const event of data.events) {
        const { event: internalEvent, childEvents } = convertEventToInternal(event, data.trace_id)
        allEvents.push(internalEvent, ...childEvents)
    }

    // Build the trace object
    const trace: LLMTrace = {
        id: data.trace_id,
        createdAt: data.timestamp,
        person: {
            uuid: 'preview-person',
            created_at: data.timestamp,
            properties: {},
            distinct_id: 'Preview User',
        },
        inputTokens: data.total_tokens?.input ?? 0,
        outputTokens: data.total_tokens?.output ?? 0,
        totalCost: data.total_cost,
        traceName: data.name,
        events: allEvents,
    }

    // Build the tree
    const tree = restoreTree(allEvents, data.trace_id)
    const enrichedTree = tree.map(enrichNode)

    return { trace, enrichedTree }
}
