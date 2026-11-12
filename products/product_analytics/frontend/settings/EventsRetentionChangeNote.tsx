import { dayjs } from 'lib/dayjs'
import { retentionPeriodLabel } from 'lib/utils/retentionPeriodLabel'

import { EventsRetentionDeletionCount } from './EventsRetentionDeletionCount'
import { EventsRetentionLevel } from './eventsRetentionDeletionCountLogic'
import { RetentionDeletion } from './retentionChangeDeletion'

export interface EventsRetentionChangeNoteProps {
    level: EventsRetentionLevel
    months: number
    scope: string
    deletion: RetentionDeletion | null
}

function deletionTiming(period: string, { monthly, deletesOn }: RetentionDeletion): string {
    const next = deletesOn ? dayjs(deletesOn).format('MMMM D, YYYY') : null
    if (monthly) {
        return `Deletion isn't instant. A cleanup runs once a month and deletes whole months of events, so some events are kept up to about a month past ${period}.${next ? ` The next cleanup is on ${next}.` : ''}`
    }
    return `Deletion isn't instant. A cleanup every 3 months deletes events past the default period, a whole month at a time, so some events are kept a few months past ${period}. ${next ? `The next one is on ${next}.` : 'The first one is at least 3 months from now.'}`
}

export function EventsRetentionChangeNote({
    level,
    months,
    scope,
    deletion,
}: EventsRetentionChangeNoteProps): JSX.Element {
    if (!deletion) {
        return <p className="mb-0">Events that were already deleted can't be restored.</p>
    }
    const period = retentionPeriodLabel(months)
    return (
        <div className="flex flex-col gap-2">
            <p className="mb-0">{`${scope} that are older than ${period} will be deleted, and deleted events can't be restored.`}</p>
            {deletion.monthly && <EventsRetentionDeletionCount count={level} months={months} />}
            <p className="mb-0">{deletionTiming(period, deletion)}</p>
        </div>
    )
}
