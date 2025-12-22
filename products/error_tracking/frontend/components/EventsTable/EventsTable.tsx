import clsx from 'clsx'

import { IconAI } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { ErrorEventType } from 'lib/components/Errors/types'
import { getExceptionAttributes, getRecordingStatus, getSessionId } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { PersonDisplay, PersonIcon } from 'scenes/persons/PersonDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import { EventsQuery } from '~/queries/schema/schema-general'

import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { cancelEvent } from '../../utils'
import { DataSourceTable, DataSourceTableColumn } from '../DataSourceTable'
import { ExceptionAttributesPreview } from '../ExceptionAttributesPreview'
import { CustomSeparator } from '../TableColumns'
import { eventsSourceLogic } from './eventsSourceLogic'

export interface EventsTableProps {
    query: EventsQuery
    queryKey: string
    selectedEvent: ErrorEventType | null
    onEventSelect: (event: ErrorEventType | null) => void
}

export function EventsTable({ query, queryKey, onEventSelect, selectedEvent }: EventsTableProps): JSX.Element {
    const tagRenderer = useErrorTagRenderer()
    const dataSource = eventsSourceLogic({ queryKey, query })

    function isEventSelected(record: ErrorEventType): boolean {
        return selectedEvent ? selectedEvent.uuid === record.uuid : false
    }

    function renderTitle(record: ErrorEventType): JSX.Element {
        return (
            <LemonTableLink
                title={
                    <div className="flex gap-x-1">
                        <Link onClick={() => onEventSelect(record)} subtle className="line-clamp-1">
                            {record.properties.$exception_types[0]}
                        </Link>
                        {tagRenderer(record)}
                    </div>
                }
                description={
                    <div className="space-y-0.5">
                        <span className="line-clamp-1">{record.properties.$exception_values[0]}</span>
                        <div className="flex items-center">
                            <div>{renderTime(record)}</div>
                            <CustomSeparator />
                            <Person person={record.person} />
                        </div>
                    </div>
                }
                className="w-full"
            />
        )
    }

    function renderAttributes(record: ErrorEventType): JSX.Element {
        return (
            <div className="flex justify-end gap-1">
                <ExceptionAttributesPreview attributes={getExceptionAttributes(record.properties)} />
            </div>
        )
    }

    function renderTime(record: ErrorEventType): JSX.Element {
        return <TZLabel time={record.timestamp} />
    }

    function renderRowSelectedIndicator(record: ErrorEventType): JSX.Element {
        return (
            <div
                className={cn(
                    'w-1 min-h-[84px]',
                    isEventSelected(record)
                        ? 'bg-primary-3000 hover:bg-primary-3000'
                        : 'hover:bg-color-accent-highlight-secondary'
                )}
            />
        )
    }

    return (
        <DataSourceTable<ErrorEventType>
            dataSource={dataSource}
            embedded
            onRowClick={(record) => onEventSelect(record)}
            className="overflow-auto"
        >
            <DataSourceTableColumn<ErrorEventType> className="p-0" cellRenderer={renderRowSelectedIndicator} />
            <DataSourceTableColumn<ErrorEventType> title="Exception" cellRenderer={renderTitle} />
            <DataSourceTableColumn<ErrorEventType> title="Labels" align="right" cellRenderer={renderAttributes} />
            <DataSourceTableColumn<ErrorEventType> title="Actions" align="right" cellRenderer={Actions} />
        </DataSourceTable>
    )
}

const Person = ({ person }: { person: ErrorEventType['person'] }): JSX.Element => {
    const display = asDisplay(person)

    return (
        <PersonDisplay person={person} noLink>
            <Link subtle className={clsx('flex items-center')}>
                <PersonIcon displayName={display} person={person} size="md" />
                <span className={clsx('ph-no-capture', 'truncate')}>{display}</span>
            </Link>
        </PersonDisplay>
    )
}

const Actions = (record: ErrorEventType): JSX.Element => {
    const sessionId = getSessionId(record.properties)
    const recordingStatus = getRecordingStatus(record.properties)
    const hasRecording = record.properties.has_recording as boolean | undefined

    return (
        <div className="flex justify-end gap-1">
            <div className="flex justify-end align-middle items-center" onClick={(event) => cancelEvent(event)}>
                <ViewRecordingButton
                    type="secondary"
                    sessionId={sessionId ?? ''}
                    recordingStatus={recordingStatus}
                    hasRecording={hasRecording}
                    timestamp={record.timestamp}
                    size="xsmall"
                    data-attr="error-tracking-view-recording"
                />
            </div>
            {record.properties.$ai_trace_id && (
                <LemonButton
                    size="small"
                    icon={<IconAI />}
                    onClick={(event) => {
                        cancelEvent(event)
                        urls.llmAnalyticsTrace(record.properties.$ai_trace_id, {
                            event: record.uuid,
                            timestamp: record.timestamp,
                        })
                    }}
                    disabledReason={
                        !record.properties.$ai_trace_id ? 'There is no LLM Trace ID on this event' : undefined
                    }
                    tooltip={record.properties.$ai_trace_id ? 'View LLM Trace' : undefined}
                />
            )}
            <LemonButton
                size="small"
                icon={<IconLink />}
                data-attr="events-table-event-link"
                onClick={(event) => {
                    cancelEvent(event)
                    void copyToClipboard(
                        urls.absolute(urls.currentProject(urls.event(String(record.uuid), record.timestamp))),
                        'link to event'
                    )
                }}
                tooltip="Copy link to exception event"
            />
        </div>
    )
}
