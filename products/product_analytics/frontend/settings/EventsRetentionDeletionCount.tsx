import { useValues } from 'kea'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import {
    EventsRetentionDeletionCountLogicProps,
    eventsRetentionDeletionCountLogic,
} from './eventsRetentionDeletionCountLogic'
import { retentionPeriodLabel } from './retentionPeriodLabel'

export function EventsRetentionDeletionCount(props: EventsRetentionDeletionCountLogicProps): JSX.Element | null {
    const { eventsDeleted, eventsDeletedLoading } = useValues(eventsRetentionDeletionCountLogic(props))

    if (eventsDeletedLoading) {
        return (
            <p className="mb-0 flex items-center gap-2 text-secondary">
                <Spinner />
                <span>Counting the events this deletes</span>
            </p>
        )
    }
    if (eventsDeleted === null) {
        return null
    }
    if (eventsDeleted === 0) {
        return <p className="mb-0">{`No events are older than ${retentionPeriodLabel(props.months)} yet.`}</p>
    }
    return (
        <p className="mb-0">
            {`This deletes about ${humanFriendlyLargeNumber(eventsDeleted)} ${eventsDeleted === 1 ? 'event' : 'events'}.`}
        </p>
    )
}
