import { useValues } from 'kea'

import { eventsDeletedSentence } from './eventsDeletedSentence'
import { eventsRetentionDeletionCountLogic } from './eventsRetentionDeletionCountLogic'

export function EventsRetentionDowngradeDeletionCount({ months }: { months: number }): JSX.Element | null {
    const { eventsDeleted } = useValues(eventsRetentionDeletionCountLogic({ count: 'downgrade', months }))

    if (!eventsDeleted) {
        return null
    }
    return <p className="mb-0 mt-2 font-semibold">{eventsDeletedSentence(eventsDeleted)}</p>
}
