import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconAI, IconEllipsis, IconLive } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { ErrorEventType } from 'lib/components/Errors/types'
import { getRecordingStatus, getRuntimeFromLib, getSessionId } from 'lib/components/Errors/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { useRecordingButton } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { IconLink, IconPlayCircle } from 'lib/lemon-ui/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Skeleton,
    SkeletonText,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableFooter,
    TableRow,
} from 'lib/ui/quill'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { EventsQuery } from '~/queries/schema/schema-general'

import { useViewLogsButton } from 'products/logs/frontend/components/ViewLogsButton'

import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { cancelEvent } from '../../utils'
import { RuntimeIcon } from '../RuntimeIcon'
import { eventsSourceLogic } from './eventsSourceLogic'

export interface EventsTableProps {
    query: EventsQuery
    queryKey: string
    selectedEvent: ErrorEventType | null
    onEventSelect: (event: ErrorEventType | null) => void
}

export function EventsTable({ query, queryKey, onEventSelect, selectedEvent }: EventsTableProps): JSX.Element {
    const dataSource = eventsSourceLogic({ queryKey, query })
    const { items, itemsLoading, canLoadNextData } = useValues(dataSource)
    const { loadNextData } = useActions(dataSource)
    const { summary } = useValues(errorTrackingIssueSceneLogic)

    function isEventSelected(record: ErrorEventType): boolean {
        return selectedEvent ? selectedEvent.uuid === record.uuid : false
    }

    function renderTitle(record: ErrorEventType): JSX.Element {
        const library = record.properties.$lib
        const runtime = getRuntimeFromLib(typeof library === 'string' ? library : null)

        return (
            <div className="grid w-full min-w-0 grid-cols-[0.75rem_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 py-0.5">
                <RuntimeIcon runtime={runtime} fontSize="0.75rem" />
                <div className="min-w-0 truncate text-sm font-semibold">{record.properties.$exception_types[0]}</div>
                <div className="col-span-2 min-w-0 truncate text-xs text-muted-foreground">
                    {record.properties.$exception_values[0]}
                </div>
            </div>
        )
    }

    function renderMetadata(record: ErrorEventType): JSX.Element {
        const hasPerson = Boolean(record.person?.id || record.person?.uuid)

        return (
            <div className="flex w-full min-w-0 flex-col items-end justify-center overflow-hidden whitespace-nowrap text-xs text-muted-foreground">
                {hasPerson && (
                    <div className="flex w-full min-w-0 justify-end overflow-hidden">
                        <Person person={record.person} />
                    </div>
                )}
                <div className="shrink-0">{renderTime(record)}</div>
            </div>
        )
    }

    function renderTime(record: ErrorEventType): JSX.Element {
        return (
            <span className="contents">
                <TZLabel time={record.timestamp} hoverOpenDelayMs={500} />
            </span>
        )
    }

    function getRowTimelineIndicatorColor(record: ErrorEventType): string {
        return record.uuid === summary?.first_event_uuid
            ? 'bg-brand-blue'
            : record.uuid === summary?.last_event_uuid
              ? 'bg-brand-red'
              : 'bg-brand-yellow'
    }

    return (
        <div data-quill>
            <Table fullWidth size="sm" tableClassName="table-fixed bg-transparent" aria-busy={itemsLoading}>
                <colgroup>
                    <col className="w-1" />
                    <col />
                </colgroup>
                {items.length > 0 ? (
                    <TableBody>
                        {items.map((record) => (
                            <TableRow
                                key={record.uuid}
                                data-state={isEventSelected(record) ? 'selected' : undefined}
                                className={cn(
                                    'cursor-pointer',
                                    isEventSelected(record)
                                        ? '[&_[data-slot=table-cell]]:!bg-[var(--fill-selected)] [&:hover_[data-slot=table-cell]]:!bg-[var(--fill-expanded)]'
                                        : '[&:hover_[data-slot=table-cell]]:!bg-[var(--fill-hover)]'
                                )}
                                onClick={() => onEventSelect(record)}
                            >
                                <TableCell className="relative w-1 p-0">
                                    <div
                                        className={cn(
                                            'absolute inset-y-0 left-0 w-1',
                                            isEventSelected(record)
                                                ? getRowTimelineIndicatorColor(record)
                                                : 'bg-transparent'
                                        )}
                                    />
                                </TableCell>
                                <TableCell className="min-w-0 overflow-hidden p-0">
                                    <div className="flex w-full min-w-0 items-center">
                                        <div className="min-w-0 flex-1 overflow-hidden px-3 py-2">
                                            {renderTitle(record)}
                                        </div>
                                        <div className="w-[35%] min-w-28 max-w-56 shrink-0 overflow-hidden py-2 pl-3 pr-4 text-right">
                                            {renderMetadata(record)}
                                        </div>
                                        <div className="flex w-10 shrink-0 justify-end py-2 pr-4">
                                            <EventActions record={record} />
                                        </div>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                ) : itemsLoading ? (
                    <EventsTableLoadingBody />
                ) : (
                    <EventsTableEmpty />
                )}
                {items.length > 0 && (
                    <TableFooter>
                        <TableRow>
                            <TableCell colSpan={2} className="bg-transparent! p-1">
                                <div className="flex h-7 items-center justify-center gap-1 text-xs text-muted-foreground">
                                    {itemsLoading ? (
                                        <>
                                            <Spinner className="size-3" />
                                            Loading...
                                        </>
                                    ) : canLoadNextData ? (
                                        <Button variant="link-muted" size="xs" onClick={() => loadNextData()}>
                                            Load more
                                        </Button>
                                    ) : (
                                        'No more entries'
                                    )}
                                </div>
                            </TableCell>
                        </TableRow>
                    </TableFooter>
                )}
            </Table>
        </div>
    )
}

export function EventsTableLoading(): JSX.Element {
    return (
        <div data-quill>
            <Table
                fullWidth
                size="sm"
                tableClassName="table-fixed bg-transparent"
                aria-busy="true"
                aria-label="Loading exceptions"
            >
                <colgroup>
                    <col className="w-1" />
                    <col />
                </colgroup>
                <EventsTableLoadingBody />
            </Table>
        </div>
    )
}

function EventsTableLoadingBody(): JSX.Element {
    return (
        <TableBody aria-hidden="true">
            {[0, 1, 2].map((row) => (
                <TableRow key={row}>
                    <TableCell className="w-1 p-0" />
                    <TableCell className="min-w-0 overflow-hidden p-0">
                        <div className="flex min-h-[56px] w-full min-w-0 items-center">
                            <div className="flex min-w-0 flex-1 flex-col gap-0.5 px-3 py-2">
                                <SkeletonText lines={1} maxWidth={40} className="text-sm" />
                                <SkeletonText lines={1} maxWidth={70} className="text-xs" />
                            </div>
                            <div className="flex w-[35%] min-w-28 max-w-56 shrink-0 flex-col items-end gap-1.5 px-3 py-2">
                                <Skeleton className="h-2.5 w-20" />
                                <Skeleton className="h-2.5 w-14" />
                            </div>
                            <div className="flex w-10 shrink-0 justify-end py-2 pr-4">
                                <Skeleton className="size-5" />
                            </div>
                        </div>
                    </TableCell>
                </TableRow>
            ))}
        </TableBody>
    )
}

function EventsTableEmpty(): JSX.Element {
    return <TableEmpty className="py-6 text-muted-foreground">No exceptions found.</TableEmpty>
}

const Person = ({ person }: { person: ErrorEventType['person'] }): JSX.Element => {
    const display = asDisplay(person)

    return (
        <span className="contents">
            <PersonDisplay person={person} noLink className="inline-flex max-w-full min-w-0 overflow-hidden">
                <Link subtle className="inline-flex max-w-full min-w-0 items-center overflow-hidden">
                    <span className="ph-no-capture truncate">{display}</span>
                </Link>
            </PersonDisplay>
        </span>
    )
}

const EventActions = ({ record }: { record: ErrorEventType }): JSX.Element => {
    const sessionId = getSessionId(record.properties)
    const recordingStatus = getRecordingStatus(record.properties)
    const hasRecording = record.properties.$has_recording as boolean | undefined
    const {
        onClick: viewRecording,
        disabledReason: recordingDisabledReason,
        warningReason: recordingWarningReason,
    } = useRecordingButton({
        sessionId: sessionId ?? '',
        recordingStatus,
        hasRecording,
        timestamp: record.timestamp,
    })
    const logs = useViewLogsButton({ sessionId, timestamp: record.timestamp })
    const recordingTooltip =
        typeof recordingDisabledReason === 'string' ? recordingDisabledReason : recordingWarningReason

    return (
        <div onClick={(event) => cancelEvent(event)}>
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button variant="default" size="icon-sm" aria-label="More actions" />}>
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-auto min-w-44">
                    <DropdownMenuItem
                        disabled={Boolean(recordingDisabledReason)}
                        onClick={viewRecording}
                        title={recordingTooltip}
                        data-attr="error-tracking-view-recording"
                    >
                        <IconPlayCircle />
                        View recording
                    </DropdownMenuItem>
                    {logs.enabled && (
                        <DropdownMenuItem
                            disabled={logs.loading || !logs.onClick}
                            onClick={logs.onClick}
                            title={logs.disabledReason}
                            data-attr="error-tracking-view-logs"
                        >
                            {logs.loading ? <Spinner /> : <IconLive />}
                            View logs
                        </DropdownMenuItem>
                    )}
                    {record.properties.$ai_trace_id && (
                        <DropdownMenuItem
                            onClick={() =>
                                router.actions.push(
                                    urls.aiObservabilityTrace(record.properties.$ai_trace_id, {
                                        event: record.uuid,
                                        timestamp: record.timestamp,
                                    })
                                )
                            }
                        >
                            <IconAI />
                            View LLM trace
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem
                        data-attr="events-table-event-link"
                        onClick={() => {
                            void copyToClipboard(
                                urls.absolute(urls.currentProject(urls.event(String(record.uuid), record.timestamp))),
                                'link to event'
                            )
                        }}
                    >
                        <IconLink />
                        Copy event link
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
