import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonEventName } from 'scenes/actions/EventName'

import { visionHogHistoryLogic } from './visionHogHistoryLogic'

const columns: LemonTableColumns<any> = [
    {
        title: 'Event',
        key: 'event',
        className: 'max-w-80',
        render: function Render(_, event) {
            return <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} />
        },
    },
    {
        title: 'Time',
        key: 'timestamp',
        className: 'max-w-80',
        render: function Render(_, event) {
            return <TZLabel time={event.timestamp} />
        },
    },
]

export function VisionHogHistory(): JSX.Element {
    const { events, filters } = useValues(visionHogHistoryLogic)
    const { setFilters } = useActions(visionHogHistoryLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex justify-end">
                <LemonEventName
                    value={filters.eventType}
                    onChange={(value) => setFilters({ ...filters, eventType: value })}
                    placeholder="Filter by event"
                    allEventsOption="clear"
                />
            </div>
            <LemonTable
                columns={columns}
                dataSource={events}
                rowKey="uuid"
                useURLForSorting={false}
                emptyState={
                    <div className="flex flex-col justify-center items-center gap-4 p-6">
                        <span className="text-lg font-title font-semibold leading-tight">No events found</span>
                    </div>
                }
                nouns={['event', 'events']}
            />
        </div>
    )
}
