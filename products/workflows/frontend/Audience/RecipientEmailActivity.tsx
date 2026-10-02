import { useValues } from 'kea'

import { engagementEventsLogic } from '../engagementEventsLogic'
import { RecipientTimeline } from './RecipientTimeline'
import { RECIPIENT_TIMELINE_DAYS, RECIPIENT_TIMELINE_LIMIT } from './recipientTimelineQuery'
import { TurnOnEngagementEvents } from './TurnOnEngagementEvents'

export function RecipientEmailActivity({ email }: { email: string }): JSX.Element {
    const { engagementEventsCaptured } = useValues(engagementEventsLogic)

    return (
        <section className="flex flex-col gap-2">
            <h3 className="font-semibold m-0">Email activity</h3>
            {engagementEventsCaptured ? (
                <>
                    <p className="m-0 text-xs text-secondary">
                        The latest {RECIPIENT_TIMELINE_LIMIT} email events for this address in the last{' '}
                        {RECIPIENT_TIMELINE_DAYS} days. The timeline follows the address, not a person, so it includes
                        every email sent to it.
                    </p>
                    <RecipientTimeline email={email} />
                </>
            ) : (
                <TurnOnEngagementEvents surface="recipient" />
            )}
        </section>
    )
}
