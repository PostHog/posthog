import { LemonTag } from '@posthog/lemon-ui'

import type { SpanAggregation } from '../llmAnalyticsTraceDataLogic'
import { formatLLMCost, formatLLMLatency } from '../utils'

export function TraceAggregationInfo({ aggregation }: { aggregation: SpanAggregation }): JSX.Element {
    return (
        <div className="flex flex-row flex-wrap items-center gap-2">
            {aggregation.totalCost > 0 && (
                <LemonTag type="muted" size="small">
                    Total Cost: {formatLLMCost(aggregation.totalCost)}
                </LemonTag>
            )}
            {aggregation.totalLatency > 0 && (
                <LemonTag type="muted" size="small">
                    Total Latency: {formatLLMLatency(aggregation.totalLatency)}
                </LemonTag>
            )}
            {(aggregation.inputTokens > 0 || aggregation.outputTokens > 0) && (
                <LemonTag type="muted" size="small">
                    Tokens: {aggregation.inputTokens} → {aggregation.outputTokens} (∑{' '}
                    {aggregation.inputTokens + aggregation.outputTokens})
                </LemonTag>
            )}
        </div>
    )
}
