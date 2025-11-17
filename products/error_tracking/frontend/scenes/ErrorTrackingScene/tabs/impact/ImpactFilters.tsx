import { useActions, useValues } from 'kea'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { errorTrackingImpactListLogic } from './errorTrackingImpactListLogic'

export function ImpactFilters(): JSX.Element {
    const { initialState } = useValues(errorTrackingImpactListLogic)

    return initialState ? <InitialState /> : <EventSelector multiple />
}

const InitialState = (): JSX.Element => {
    return (
        <div className="flex flex-col items-center text-center py-12">
            <h2 className="text-xl font-bold">Understand the impact of issues</h2>
            <div className="text-sm text-secondary mb-2">
                See what issues are causing the most impact on your conversion, activation or any other event you're
                tracking in PostHog.
            </div>

            <EventSelector multiple={false} />
        </div>
    )
}

const EventSelector = ({ multiple }: { multiple: boolean }): JSX.Element => {
    const { events } = useValues(errorTrackingImpactListLogic)
    const { setEvent, setEvents } = useActions(errorTrackingImpactListLogic)

    return (
        <TaxonomicPopover<string | null>
            size="small"
            type="secondary"
            groupType={TaxonomicFilterGroupType.Events}
            onChange={(event) => (event ? setEvent(event) : setEvents([]))}
            allowClear
            selectedProperties={{ [TaxonomicFilterGroupType.Events]: events ?? undefined }}
            excludedProperties={{ [TaxonomicFilterGroupType.Events]: [null, '$exception'] }}
            placeholder={multiple ? 'Select events' : 'Select an event'}
            placement="bottom"
            closeOnChange={!multiple}
            value={events ? events[0] : null}
            renderValue={(value) => (
                <div className="flex gap-x-1">
                    <PropertyKeyInfo value={value} disablePopover type={TaxonomicFilterGroupType.Events} />
                    {events!.length > 1 ? <span className="text-muted">+ {events!.length - 1} more</span> : null}
                </div>
            )}
        />
    )
}
