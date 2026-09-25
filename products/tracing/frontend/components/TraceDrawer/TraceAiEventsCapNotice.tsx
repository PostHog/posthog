import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MAX_AI_EVENTS_PER_TRACE, type TraceAiEvent } from '../../aiEventSpans'

export interface TraceAiEventsCapNoticeProps {
    aiEvents: TraceAiEvent[]
    hasMore: boolean
}

export function TraceAiEventsCapNotice({ aiEvents, hasMore }: TraceAiEventsCapNoticeProps): JSX.Element | null {
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
            This trace has more than {MAX_AI_EVENTS_PER_TRACE} AI events. The waterfall shows the first{' '}
            {MAX_AI_EVENTS_PER_TRACE}.
        </LemonBanner>
    )
}
