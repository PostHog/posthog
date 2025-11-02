import { Spinner } from 'lib/lemon-ui/Spinner'

import { LLMTrace } from '~/queries/schema/schema-general'

import { LLMAnalyticsEventCard } from './LLMAnalyticsEventCard'

interface LLMAnalyticsTraceEventsProps {
    trace: LLMTrace | undefined
    isLoading: boolean
    expandedEventIds: Set<string>
    onToggleEventExpand: (eventId: string) => void
}

export function LLMAnalyticsTraceEvents({
    trace,
    isLoading,
    expandedEventIds,
    onToggleEventExpand,
}: LLMAnalyticsTraceEventsProps): JSX.Element {
    if (isLoading) {
        return <Spinner />
    }

    if (!trace) {
        return <div className="text-muted text-sm">Failed to load trace details</div>
    }

    const allEvents =
        trace.events
            ?.filter((e) => e.event === '$ai_generation' || e.event === '$ai_span')
            .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()) || []

    if (allEvents.length === 0) {
        return (
            <div className="text-muted text-sm">
                No generation or span events found in this trace.
                {trace.events ? ` (Trace has ${trace.events.length} total events)` : ' (No events loaded)'}
            </div>
        )
    }

    return (
        <>
            {allEvents.map((event) => (
                <LLMAnalyticsEventCard
                    key={event.id}
                    event={event}
                    isExpanded={expandedEventIds.has(event.id)}
                    onToggleExpand={() => onToggleEventExpand(event.id)}
                />
            ))}
        </>
    )
}
