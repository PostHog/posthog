import { Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { ErrorEventType } from 'lib/components/Errors/types'
import { getExceptionAttributes, getSessionId } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton, { mightHaveRecording } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay, PersonIcon } from 'scenes/persons/PersonDisplay'

import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { cancelEvent } from '../../utils'
import { DataSourceTable, DataSourceTableColumn } from '../DataSourceTable'
import { ExceptionAttributesPreview } from '../ExceptionAttributesPreview'
import { eventsQueryLogic } from './eventsQueryLogic'
import { eventsSourceLogic } from './eventsSourceLogic'

export interface EventsTableProps {
    issueId: string
    selectedEvent: ErrorEventType | null
    onEventSelect: (event: ErrorEventType | null) => void
}

function renderViewRecordingButton(event: ErrorEventType): JSX.Element {
    const sessionId = getSessionId(event.properties)
    const hasRecording = mightHaveRecording(event.properties || {})
    return (
        <span onClick={cancelEvent}>
            <ViewRecordingButton
                sessionId={sessionId}
                timestamp={event.timestamp ?? undefined}
                inModal={true}
                size="xsmall"
                type="secondary"
                disabledReason={hasRecording ? undefined : 'No recording available'}
            />
        </span>
    )
}

export function EventsTable({ issueId, selectedEvent, onEventSelect }: EventsTableProps): JSX.Element {
    const { query, queryKey } = useValues(eventsQueryLogic({ issueId }))
    const tagRenderer = useErrorTagRenderer()
    const dataSource = eventsSourceLogic({ queryKey, query })

    function isEventSelected(record: ErrorEventType): boolean {
        return selectedEvent ? selectedEvent.uuid === record.uuid : false
    }

    function toggleSelectedEvent(record: ErrorEventType): void {
        return isEventSelected(record) ? onEventSelect(null) : onEventSelect(record)
    }

    function renderUUID(record: ErrorEventType): JSX.Element {
        // Click event is caught at the row level
        return (
            <div className="flex items-center">
                <input type="radio" className="cursor-pointer" checked={isEventSelected(record)} />
            </div>
        )
    }

    function renderPerson(record: ErrorEventType): JSX.Element {
        const display = asDisplay(record.person)
        return (
            <div className="flex items-center">
                <span onClick={cancelEvent}>
                    <PersonDisplay person={record.person} noLink>
                        <Link subtle className={clsx('flex items-center')}>
                            <PersonIcon displayName={display} person={record.person} size="md" />
                            <span className={clsx('ph-no-capture', 'truncate')}>{display}</span>
                        </Link>
                    </PersonDisplay>
                </span>
            </div>
        )
    }

    function renderAttributes(record: ErrorEventType): JSX.Element {
        return (
            <div className="flex justify-end gap-1">
                {tagRenderer(record)}
                <ExceptionAttributesPreview attributes={getExceptionAttributes(record.properties)} />
            </div>
        )
    }

    function renderRecording(record: ErrorEventType): JSX.Element {
        return <div className="flex justify-end">{renderViewRecordingButton(record)}</div>
    }

    function renderTime(record: ErrorEventType): JSX.Element {
        return <TZLabel time={record.timestamp} />
    }

    return (
        <DataSourceTable<ErrorEventType> dataSource={dataSource} embedded onRowClick={toggleSelectedEvent}>
            <DataSourceTableColumn<ErrorEventType> width="40px" cellRenderer={renderUUID} />
            <DataSourceTableColumn<ErrorEventType> title="Person" cellRenderer={renderPerson} />
            <DataSourceTableColumn<ErrorEventType> title="Time" cellRenderer={renderTime} />
            <DataSourceTableColumn<ErrorEventType> title="Labels" align="right" cellRenderer={renderAttributes} />
            <DataSourceTableColumn<ErrorEventType> title="Recording" align="right" cellRenderer={renderRecording} />
        </DataSourceTable>
    )
}
