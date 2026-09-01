import { useEffect, useRef } from 'react'

import { Link } from '@posthog/lemon-ui'

import { ErrorEventType } from 'lib/components/Errors/types'
import { getExceptionTypeAndValue, getRuntimeFromLib } from 'lib/components/Errors/utils'
import type { TimelineMarkerColor } from 'lib/components/SessionTimeline/SessionTimeline'
import { TZLabel } from 'lib/components/TZLabel'
import {
    Button,
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
import { cn } from 'lib/utils/css-classes'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { RuntimeIcon } from '../RuntimeIcon'
import { EventActions } from './EventActions'

export interface EventsTableProps {
    items: ErrorEventType[]
    loading: boolean
    hasMore: boolean
    selectedEvent: ErrorEventType | null
    firstEventUuid?: string
    lastEventUuid?: string
    onEventSelect: (event: ErrorEventType) => void
    onLoadMore: () => void
}

export function EventsTable({
    items,
    loading,
    hasMore,
    selectedEvent,
    firstEventUuid,
    lastEventUuid,
    onEventSelect,
    onLoadMore,
}: EventsTableProps): JSX.Element {
    return (
        <div data-quill>
            <Table fullWidth size="sm" tableClassName="table-fixed bg-transparent" aria-busy={loading}>
                <colgroup>
                    <col className="w-1" />
                    <col />
                </colgroup>
                {items.length > 0 ? (
                    <TableBody>
                        {items.map((record) => (
                            <EventRow
                                key={record.uuid}
                                record={record}
                                selected={selectedEvent?.uuid === record.uuid}
                                firstEventUuid={firstEventUuid}
                                lastEventUuid={lastEventUuid}
                                onSelect={onEventSelect}
                            />
                        ))}
                    </TableBody>
                ) : loading ? (
                    <EventsTableLoadingBody />
                ) : (
                    <EventsTableEmpty />
                )}
                {items.length > 0 && (
                    <TableFooter>
                        <TableRow>
                            <TableCell colSpan={2} className="bg-transparent! p-1">
                                <div className="flex h-7 items-center justify-center gap-1 text-xs text-muted-foreground">
                                    {loading ? (
                                        <>
                                            <Spinner className="size-3" />
                                            Loading...
                                        </>
                                    ) : hasMore ? (
                                        <Button variant="link-muted" size="xs" onClick={onLoadMore}>
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

function EventRow({
    record,
    selected,
    firstEventUuid,
    lastEventUuid,
    onSelect,
}: {
    record: ErrorEventType
    selected: boolean
    firstEventUuid?: string
    lastEventUuid?: string
    onSelect: (event: ErrorEventType) => void
}): JSX.Element {
    const rowRef = useRef<HTMLTableRowElement>(null)

    // Scroll only when this row becomes the selected one. Depending on the list's loading state
    // would re-fire on every pagination request and yank the list back to the selection.
    useEffect(() => {
        if (selected) {
            rowRef.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [selected])

    return (
        <TableRow
            ref={rowRef}
            data-state={selected ? 'selected' : undefined}
            className={cn(
                'cursor-pointer',
                selected
                    ? '[&_[data-slot=table-cell]]:!bg-[var(--fill-selected)] [&:hover_[data-slot=table-cell]]:!bg-[var(--fill-expanded)]'
                    : '[&:hover_[data-slot=table-cell]]:!bg-[var(--fill-hover)]'
            )}
            onClick={() => onSelect(record)}
        >
            <TableCell className="relative w-1 p-0">
                <div
                    className={cn(
                        'absolute inset-y-0 left-0 w-1',
                        selected
                            ? EVENT_MARKER_COLOR_CLASS_NAMES[
                                  getEventMarkerColor(record.uuid, firstEventUuid, lastEventUuid)
                              ]
                            : 'bg-transparent'
                    )}
                />
            </TableCell>
            <TableCell className="min-w-0 overflow-hidden p-0">
                <div className="flex w-full min-w-0 items-center">
                    <div className="min-w-0 flex-1 overflow-hidden px-3 py-2">
                        <EventTitle record={record} />
                    </div>
                    <div className="w-[35%] min-w-28 max-w-56 shrink-0 overflow-hidden py-2 pl-3 pr-4 text-right">
                        <EventMetadata record={record} />
                    </div>
                    <div className="flex w-10 shrink-0 justify-end py-2 pr-4">
                        <EventActions record={record} />
                    </div>
                </div>
            </TableCell>
        </TableRow>
    )
}

function EventTitle({ record }: { record: ErrorEventType }): JSX.Element {
    const library = record.properties.$lib
    const runtime = getRuntimeFromLib(typeof library === 'string' ? library : null)
    const { type, value } = getExceptionTypeAndValue(record.properties)

    return (
        <div className="grid w-full min-w-0 grid-cols-[0.75rem_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 py-0.5">
            <RuntimeIcon runtime={runtime} fontSize="0.75rem" />
            <div className="min-w-0 truncate text-sm font-semibold">
                {type ?? <span className="italic text-muted-foreground">Unknown</span>}
            </div>
            <div className="col-span-2 min-w-0 truncate text-xs text-muted-foreground">
                {value ?? <span className="italic">No message</span>}
            </div>
        </div>
    )
}

function EventMetadata({ record }: { record: ErrorEventType }): JSX.Element {
    const hasPerson = Boolean(record.person?.id || record.person?.uuid)

    return (
        <div className="flex w-full min-w-0 flex-col items-end justify-center overflow-hidden whitespace-nowrap text-xs text-muted-foreground">
            {hasPerson && (
                <div className="flex w-full min-w-0 justify-end overflow-hidden">
                    <Person person={record.person} />
                </div>
            )}
            <div className="shrink-0">
                <span className="contents">
                    <TZLabel time={record.timestamp} hoverOpenDelayMs={500} />
                </span>
            </div>
        </div>
    )
}

const EVENT_MARKER_COLOR_CLASS_NAMES: Record<TimelineMarkerColor, string> = {
    blue: 'bg-brand-blue',
    yellow: 'bg-brand-yellow',
    red: 'bg-brand-red',
}

export function getEventMarkerColor(
    eventUuid: string,
    firstEventUuid: string | undefined,
    lastEventUuid: string | undefined
): TimelineMarkerColor {
    return eventUuid === firstEventUuid ? 'blue' : eventUuid === lastEventUuid ? 'red' : 'yellow'
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
