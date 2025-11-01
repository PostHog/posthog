/**
 * Format metadata section for text view: provider, model, tokens, latency, status
 */
import { LLMTraceEvent } from '~/queries/schema/schema-general'

export function formatMetadata(event: LLMTraceEvent): string[] {
    const lines: string[] = []
    const props = event.properties

    // Provider and model
    const provider = props.$ai_provider || 'N/A'
    const model = props.$ai_model || 'N/A'
    lines.push(`Provider: ${provider}`)
    lines.push(`Model: ${model}`)

    // Token usage
    const inputTokens = props.$ai_input_tokens || 0
    const outputTokens = props.$ai_output_tokens || 0
    const reasoningTokens = props.$ai_reasoning_tokens || 0
    const cacheCreation = props.$ai_cache_creation_input_tokens || 0
    const cacheRead = props.$ai_cache_read_input_tokens || 0

    if (inputTokens || outputTokens || reasoningTokens) {
        lines.push(
            `Tokens: in=${inputTokens}, out=${outputTokens}${reasoningTokens ? `, reasoning=${reasoningTokens}` : ''}`
        )
        if (cacheCreation || cacheRead) {
            lines.push(`Cache: creation=${cacheCreation}, read=${cacheRead}`)
        }
    }

    // Latency
    const latency = props.$ai_latency
    if (latency != null) {
        lines.push(`Latency: ${Number(latency).toFixed(3)}s`)
    }

    // Cost
    const totalCost = props.$ai_total_cost_usd
    if (totalCost != null && Number(totalCost) > 0) {
        lines.push(`Cost: $${Number(totalCost).toFixed(4)}`)
    }

    // HTTP status
    const status = props.$ai_http_status
    if (status != null) {
        lines.push(`HTTP Status: ${status}`)
    }

    // Error info
    const isError = props.$ai_is_error
    const errorMsg = props.$ai_error
    if (isError || errorMsg) {
        if (errorMsg) {
            lines.push(`Error: ${errorMsg}`)
        } else {
            lines.push('Error: true')
        }
    }

    return lines
}
