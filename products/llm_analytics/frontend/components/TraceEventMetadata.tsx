import type { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { MetadataHeader } from '../ConversationDisplay/MetadataHeader'
import { isLLMEvent } from '../utils'

export function TraceEventMetadata({
    event,
    showStreamingMetadata = false,
}: {
    event: LLMTrace | LLMTraceEvent
    showStreamingMetadata?: boolean
}): JSX.Element {
    return isLLMEvent(event) ? (
        <MetadataHeader
            isError={event.properties.$ai_is_error}
            inputTokens={event.properties.$ai_input_tokens}
            outputTokens={event.properties.$ai_output_tokens}
            cacheReadTokens={event.properties.$ai_cache_read_input_tokens}
            cacheWriteTokens={event.properties.$ai_cache_creation_input_tokens}
            totalCostUsd={event.properties.$ai_total_cost_usd}
            model={event.properties.$ai_model}
            latency={event.properties.$ai_latency}
            timestamp={event.createdAt}
            timeToFirstToken={showStreamingMetadata ? event.properties.$ai_time_to_first_token : undefined}
            isStreaming={showStreamingMetadata ? event.properties.$ai_stream === true : undefined}
        />
    ) : (
        <MetadataHeader
            inputTokens={event.inputTokens}
            outputTokens={event.outputTokens}
            totalCostUsd={event.totalCost}
            latency={event.totalLatency}
            timestamp={event.createdAt}
        />
    )
}
