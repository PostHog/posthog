import { IconClock } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { colonDelimitedDuration } from 'lib/utils'

import { PatternAssignedEventSegmentContext } from './types'

export function SessionGroupSummaryDetailsMetadata({
    event,
    issueTags,
}: {
    event: PatternAssignedEventSegmentContext
    issueTags?: JSX.Element[]
}): JSX.Element {
    const sessionId = event.target_event.session_id
    const issueTime = colonDelimitedDuration(event.target_event.milliseconds_since_start / 1000)
    const sessionDuration = event.session_duration !== null ? colonDelimitedDuration(event.session_duration) : 'N/A'

    return (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
            <div className="flex flex-wrap items-center gap-2">
                <span>{sessionId}</span>
                <span className="hidden sm:inline">·</span>
                <span className="flex items-center gap-1">
                    <IconClock className="text-muted" />
                    {issueTime}/{sessionDuration}
                </span>
                <span className="hidden sm:inline">·</span>
                <TZLabel time={event.target_event.timestamp} className="text-xs" />
                {event.person_email && (
                    <>
                        <span className="hidden sm:inline">·</span>
                        <span>{event.person_email}</span>
                    </>
                )}
            </div>
            {issueTags && issueTags.length > 0 && <div className="flex items-center gap-1">{issueTags}</div>}
        </div>
    )
}
