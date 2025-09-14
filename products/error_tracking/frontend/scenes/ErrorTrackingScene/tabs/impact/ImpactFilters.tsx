import { useActions, useValues } from 'kea'

import { EventName } from 'products/actions/frontend/components/EventName'

import { errorTrackingImpactListLogic } from './errorTrackingImpactListLogic'

export function ImpactFilters(): JSX.Element {
    const { initialState } = useValues(errorTrackingImpactListLogic)

    return initialState ? <InitialState /> : <EventSelector />
}

const InitialState = (): JSX.Element => {
    return (
        <div className="flex flex-col items-center text-center py-12">
            <h2 className="text-xl font-bold">Understand the impact of issues</h2>
            <div className="text-sm text-secondary mb-2">
                See what issues are causing the most impact on your conversion, activation or any other event you're
                tracking in PostHog.
            </div>

            <EventSelector />
        </div>
    )
}

const EventSelector = (): JSX.Element => {
    const { events } = useValues(errorTrackingImpactListLogic)
    const { setEvents } = useActions(errorTrackingImpactListLogic)

    return (
        <EventName
            value={events && events.length > 0 ? events[0] : null}
            onChange={(event) => setEvents(event ? [event] : [])}
            allEventsOption="clear"
            placement="bottom"
        />
    )
}
