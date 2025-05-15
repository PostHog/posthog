import { IconPauseFilled, IconPlayFilled } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { EventDetails } from 'scenes/activity/explore/EventDetails'

import { EventCopyLinkButton } from '~/queries/nodes/DataTable/EventRowActions'
import type { LiveEvent } from '~/types'

import { liveEventsTableLogic } from './liveEventsTableLogic'

const columns: LemonTableColumns<LiveEvent> = [
    {
        title: 'Event',
        key: 'event',
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} />
        },
    },
    {
        title: 'Time',
        key: 'timestamp',
        className: 'max-w-80',
        render: function Render(_, event: LiveEvent) {
            return <TZLabel time={event.timestamp} />
        },
    },
    {
        dataIndex: '__more' as any,
        render: function Render(_, event: LiveEvent) {
            return (
                <More
                    overlay={
                        <Tooltip title="It may take up to a few minutes for the event to show up in the Explore view">
                            <EventCopyLinkButton event={event} />
                        </Tooltip>
                    }
                />
            )
        },
        width: 0,
    },
]

export function LiveEventsTable(): JSX.Element {
    const { events, streamPaused } = useValues(liveEventsTableLogic)
    const { pauseStream, resumeStream } = useActions(liveEventsTableLogic)

    return (
        <div data-attr="manage-events-table">
            <div className="mb-4 flex w-full justify-between items-center">
                <div className="flex gap-2">
                    <LemonButton
                        icon={
                            streamPaused ? (
                                <IconPlayFilled className="w-4 h-4" />
                            ) : (
                                <IconPauseFilled className="w-4 h-4" />
                            )
                        }
                        type="secondary"
                        onClick={streamPaused ? resumeStream : pauseStream}
                        size="small"
                    >
                        {streamPaused ? 'Play' : 'Pause'}
                    </LemonButton>
                </div>
            </div>
            <LemonTable
                columns={columns}
                data-attr="live-events-table"
                rowKey="uuid"
                dataSource={events}
                useURLForSorting={false}
                expandable={{
                    expandedRowRender: (record) => (
                        <div className="p-2">
                            <EventDetails event={record} />
                        </div>
                    ),
                    rowExpandable: () => true,
                }}
                emptyState={
                    <div className="flex flex-col justify-center items-center gap-4 p-6">
                        {!streamPaused ? (
                            <Spinner className="text-4xl" textColored />
                        ) : (
                            <IconPauseFilled className="text-4xl" />
                        )}
                        <span className="text-lg font-title font-semibold leading-tight">
                            {!streamPaused ? 'Waiting for events…' : 'Stream paused'}
                        </span>
                    </div>
                }
                nouns={['event', 'events']}
            />
        </div>
    )
}
