import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EnrichedTraceTreeNode } from './llmAnalyticsTraceDataLogic'
import { CompatMessage } from './types'
import { formatLLMEventTitle, normalizeMessages } from './utils'

interface EventMetrics {
    latency?: number
    tokens?: {
        input: number
        output: number
    }
    cost?: number
}

interface TokenUsage {
    input: number
    output: number
}

interface MinimalTraceExport {
    trace_id: string
    name?: string
    timestamp: string
    total_cost?: number
    total_tokens: TokenUsage
    events: MinimalEventExport[]
}

interface MinimalEventExport {
    type: 'generation' | 'span' | 'trace'
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

function buildEventExport(event: LLMTraceEvent, children?: EnrichedTraceTreeNode[]): MinimalEventExport {
    const isGeneration = event.event === '$ai_generation'
    const type = isGeneration ? 'generation' : 'span'

    const result: MinimalEventExport = {
        type,
        name: formatLLMEventTitle(event),
    }

    // Add model and provider for generations
    if (isGeneration) {
        if (event.properties.$ai_model) {
            result.model = event.properties.$ai_model
        }
        if (event.properties.$ai_provider) {
            result.provider = event.properties.$ai_provider
        }
    }

    // Handle input/output based on event type
    if (isGeneration) {
        // For generations, normalize messages without tools
        const inputMessages: CompatMessage[] = normalizeMessages(event.properties.$ai_input, 'user')
        const outputMessages: CompatMessage[] = normalizeMessages(
            event.properties.$ai_output_choices ?? event.properties.$ai_output,
            'assistant'
        )

        const messages: CompatMessage[] = []
        if (inputMessages.length > 0) {
            messages.push(...inputMessages)
        }
        if (outputMessages.length > 0) {
            messages.push(...outputMessages)
        }
        if (messages.length > 0) {
            result.messages = messages
        }

        // Add available tools separately if present
        if (event.properties.$ai_tools) {
            result.available_tools = event.properties.$ai_tools
        }
    } else {
        // For spans, include raw input/output
        if (event.properties.$ai_input_state !== undefined) {
            result.input = event.properties.$ai_input_state
        }
        if (event.properties.$ai_output_state !== undefined) {
            result.output = event.properties.$ai_output_state
        }
    }

    // Add error information if present
    if (event.properties.$ai_error) {
        result.error = event.properties.$ai_error
    } else if (event.properties.$ai_is_error) {
        result.error = 'Error occurred (details not available)'
    }

    // Add metrics
    const metrics: EventMetrics = {}
    if (event.properties.$ai_latency) {
        metrics.latency = event.properties.$ai_latency
    }
    if (event.properties.$ai_input_tokens || event.properties.$ai_output_tokens) {
        metrics.tokens = {
            input: event.properties.$ai_input_tokens || 0,
            output: event.properties.$ai_output_tokens || 0,
        }
    }
    if (event.properties.$ai_total_cost_usd) {
        metrics.cost = event.properties.$ai_total_cost_usd
    }

    if (Object.keys(metrics).length > 0) {
        result.metrics = metrics
    }

    // Add children if they exist
    if (children && children.length > 0) {
        result.children = children.map((child) => buildEventExport(child.event, child.children))
    }

    return result
}

export function buildMinimalTraceJSON(trace: LLMTrace, tree: EnrichedTraceTreeNode[]): MinimalTraceExport {
    const result: MinimalTraceExport = {
        trace_id: trace.id,
        timestamp: trace.createdAt,
        total_tokens: {
            input: trace.inputTokens || 0,
            output: trace.outputTokens || 0,
        },
        events: tree.map((node) => buildEventExport(node.event, node.children)),
    }

    // Add trace name if available
    if (trace.traceName) {
        result.name = trace.traceName
    }

    // Add total cost if available
    if (trace.totalCost) {
        result.total_cost = trace.totalCost
    }

    return result
}

export async function exportTraceToClipboard(trace: LLMTrace, tree: EnrichedTraceTreeNode[]): Promise<void> {
    const exportData = buildMinimalTraceJSON(trace, tree)
    const jsonString = JSON.stringify(exportData, null, 2)

    await copyToClipboard(jsonString, 'trace data')
}
