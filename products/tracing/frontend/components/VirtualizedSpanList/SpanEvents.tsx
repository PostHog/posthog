import type { _SpanEventApi } from 'products/tracing/frontend/generated/api.schemas'

import { formatDuration, parseTimestampUs } from '../../spanTime'
import { SpanAttributes } from './SpanAttributes'

export interface SpanEventsProps {
    events: _SpanEventApi[]
    /** Span start time. Each event shows its offset from this time. */
    spanTimestamp: string
}

function formatOffset(offsetUs: number): string {
    return `${offsetUs < 0 ? '-' : '+'}${formatDuration(Math.abs(offsetUs) * 1_000)}`
}

export function SpanEvents({ events, spanTimestamp }: SpanEventsProps): JSX.Element {
    const spanStartUs = parseTimestampUs(spanTimestamp)
    return (
        <>
            {events.map((event, index) => (
                <SpanAttributes
                    key={index}
                    title={`Event: ${event.name || 'unnamed'}`}
                    subtitle={
                        event.timestamp ? formatOffset(parseTimestampUs(event.timestamp) - spanStartUs) : undefined
                    }
                    subtitleTooltip={event.timestamp ?? undefined}
                    attributes={event.attributes}
                    emptyLabel="No attributes on this event"
                    showFilterActions={false}
                />
            ))}
        </>
    )
}
