import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { TraceAiEvent } from '../../aiEventSpans'

export interface TraceAiEventsCapNoticeProps {
    aiEvents: TraceAiEvent[]
    hasMore: boolean
    limit: number
}

export function TraceAiEventsCapNotice({ aiEvents, hasMore, limit }: TraceAiEventsCapNoticeProps): JSX.Element | null {
    if (!hasMore || aiEvents.length === 0) {
        return null
    }
    return (
        <LemonBanner
            type="info"
            className="mb-2"
            action={{
                children: 'View all in AI observability',
                to: urls.aiObservabilityTrace(aiEvents[0].ai_trace_id),
                targetBlank: true,
                'data-attr': 'tracing-ai-events-view-all',
            }}
        >
            This trace has more than {limit} AI events. The waterfall shows the first {limit}.
        </LemonBanner>
    )
}
