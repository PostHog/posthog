import { TZLabel } from 'lib/components/TZLabel'
import { colonDelimitedDuration } from 'lib/utils'

import { PatternAssignedEventSegmentContext } from './types'

export function SessionGroupSummaryDetailsMetadata({
    event,
}: {
    event: PatternAssignedEventSegmentContext
}): JSX.Element {
    const sessionId = event.target_event.session_id
    const duration = event.session_duration !== null ? colonDelimitedDuration(event.session_duration) : 'N/A'

    return (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>{sessionId}</span>
            <span className="hidden sm:inline">·</span>
            <span>{duration}</span>
            <span className="hidden sm:inline">·</span>
            <TZLabel time={event.target_event.timestamp} className="text-xs" />
            {event.person_email && (
                <>
                    <span className="hidden sm:inline">·</span>
                    <span>{event.person_email}</span>
                </>
            )}
        </div>
    )
}
