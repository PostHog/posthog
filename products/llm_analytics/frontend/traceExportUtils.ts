import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { TraceTreeNode, restoreTree } from './llmAnalyticsTraceDataLogic'
import { EventMetrics, MinimalEventExport, MinimalTraceExport } from './traceImportUtils'
import { CompatMessage } from './types'
import { formatLLMEventTitle, normalizeMessages } from './utils'

function buildEventExport(event: LLMTraceEvent, children?: TraceTreeNode[]): MinimalEventExport {
    const isGeneration = event.event === '$ai_generation'
    const isEmbedding = event.event === '$ai_embedding'
    const isTraceEvent = event.event === '$ai_trace'
    const type = isGeneration ? 'generation' : isEmbedding ? 'embedding' : isTraceEvent ? 'trace' : 'span'

    const result: MinimalEventExport = {
        type,
        name: formatLLMEventTitle(event),
    }

    // Add model and provider for generations and embeddings
    if (isGeneration || isEmbedding) {
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
    } else if (isEmbedding) {
        // For embeddings, store the input text
        if (event.properties.$ai_input !== undefined) {
            result.input = event.properties.$ai_input
        }
        // Output is just "Embedding vector generated" - no need to store
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
    if (typeof event.properties.$ai_latency === 'number') {
        metrics.latency = event.properties.$ai_latency
    }
    if (typeof event.properties.$ai_time_to_first_token === 'number') {
        metrics.time_to_first_token = event.properties.$ai_time_to_first_token
    }
    if (
        typeof event.properties.$ai_input_tokens === 'number' ||
        typeof event.properties.$ai_output_tokens === 'number'
    ) {
        metrics.tokens = {
            input: event.properties.$ai_input_tokens ?? 0,
            output: event.properties.$ai_output_tokens ?? 0,
        }
    }
    if (typeof event.properties.$ai_total_cost_usd === 'number') {
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

export function buildMinimalTraceJSON(trace: LLMTrace): MinimalTraceExport {
    const tree = restoreTree(trace.events, trace.id)
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

    if (trace.inputState !== undefined) {
        result.input = trace.inputState
    }

    if (trace.outputState !== undefined) {
        result.output = trace.outputState
    }

    if (typeof trace.inputCost === 'number') {
        result.input_cost = trace.inputCost
    }

    if (typeof trace.outputCost === 'number') {
        result.output_cost = trace.outputCost
    }

    if (typeof trace.totalCost === 'number') {
        result.total_cost = trace.totalCost
    }

    if (typeof trace.totalLatency === 'number') {
        result.total_latency = trace.totalLatency
    }

    return result
}

export async function exportTraceToClipboard(trace: LLMTrace): Promise<void> {
    const exportData = buildMinimalTraceJSON(trace)
    const jsonString = JSON.stringify(exportData, null, 2)

    await copyToClipboard(jsonString, 'trace data')
}
