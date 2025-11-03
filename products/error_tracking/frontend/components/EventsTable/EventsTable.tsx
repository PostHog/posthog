import clsx from 'clsx'

import { IconAI } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { ErrorEventType } from 'lib/components/Errors/types'
import { getExceptionAttributes, getRecordingStatus, getSessionId } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { useRecordingButton } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { IconLink, IconPlayCircle } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { isString } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { PersonDisplay, PersonIcon } from 'scenes/persons/PersonDisplay'
import { asDisplay } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'

import { EventsQuery } from '~/queries/schema/schema-general'

import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { cancelEvent } from '../../utils'
import { DataSourceTable, DataSourceTableColumn } from '../DataSourceTable'
import { ExceptionAttributesPreview } from '../ExceptionAttributesPreview'
import { eventsSourceLogic } from './eventsSourceLogic'

export interface EventsTableProps {
    query: EventsQuery
    queryKey: string
    selectedEvent: ErrorEventType | null
    onEventSelect: (event: ErrorEventType | null) => void
}

export function EventsTable({ query, queryKey, selectedEvent, onEventSelect }: EventsTableProps): JSX.Element {
    const hasNewIssueLayout = useFeatureFlag('ERROR_TRACKING_ISSUE_LAYOUT_V2')
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
                <input type="radio" className="cursor-pointer" checked={isEventSelected(record)} onChange={() => {}} />
            </div>
        )
    }

    function renderTitle(record: ErrorEventType): JSX.Element {
        return (
            <LemonTableLink
                onClick={() => onEventSelect(record)}
                title={record.properties.$exception_types[0]}
                description={
                    <div>
                        <span>{record.properties.$exception_values[0]}</span>
                        <div>{renderTime(record)}</div>
                        <ExceptionAttributesPreview attributes={getExceptionAttributes(record.properties)} />
                        {tagRenderer(record)}
                    </div>
                }
            />
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

    function renderTime(record: ErrorEventType): JSX.Element {
        return <TZLabel time={record.timestamp} />
    }

    return (
        <DataSourceTable<ErrorEventType>
            dataSource={dataSource}
            embedded
            onRowClick={hasNewIssueLayout ? undefined : toggleSelectedEvent}
            className="overflow-auto"
        >
            <DataSourceTableColumn<ErrorEventType>
                width="200px"
                title="Exeption"
                cellRenderer={hasNewIssueLayout ? renderTitle : renderUUID}
            />
            <DataSourceTableColumn<ErrorEventType> width="100px" title="Person" cellRenderer={renderPerson} />
            {!hasNewIssueLayout && (
                <>
                    <DataSourceTableColumn<ErrorEventType> title="Time" cellRenderer={renderTime} />
                    <DataSourceTableColumn<ErrorEventType>
                        title="Labels"
                        align="right"
                        cellRenderer={renderAttributes}
                    />
                </>
            )}
            <DataSourceTableColumn<ErrorEventType> title="Actions" align="right" cellRenderer={Actions} />
        </DataSourceTable>
    )
}

const Actions = (record: ErrorEventType): JSX.Element => {
    const { onClick: onClickRecordingButton, disabledReason } = useRecordingButton({
        sessionId: getSessionId(record.properties),
        recordingStatus: getRecordingStatus(record.properties),
        timestamp: record.timestamp,
        inModal: true,
    })

    return (
        <div className="flex justify-end">
            <ButtonPrimitive
                disabledReasons={isString(disabledReason) ? { [disabledReason]: true } : {}}
                onClick={(event) => {
                    cancelEvent(event)
                    onClickRecordingButton()
                }}
                tooltip="View recording"
            >
                <IconPlayCircle />
            </ButtonPrimitive>
            {record.properties.$ai_trace_id && (
                <ButtonPrimitive
                    fullWidth
                    onClick={(event) => {
                        cancelEvent(event)
                        urls.llmAnalyticsTrace(record.properties.$ai_trace_id, {
                            event: record.uuid,
                            timestamp: record.timestamp,
                        })
                    }}
                    disabledReasons={{ ['There is no LLM Trace ID on this event']: !record.properties.$ai_trace_id }}
                    tooltip="View LLM Trace"
                >
                    <IconAI />
                </ButtonPrimitive>
            )}
            <ButtonPrimitive
                data-attr="events-table-event-link"
                onClick={(event) => {
                    cancelEvent(event)
                    void copyToClipboard(
                        urls.absolute(urls.currentProject(urls.event(String(record.uuid), record.timestamp))),
                        'link to event'
                    )
                }}
                tooltip="Copy link to exception event"
            >
                <IconLink />
            </ButtonPrimitive>
        </div>
    )
}
