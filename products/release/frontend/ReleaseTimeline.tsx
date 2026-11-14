import { CellContext, ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { createContext, memo, useContext, useEffect, useMemo, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { DataTable, Text, cn } from '@posthog/quill'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { RolloutStep } from './releaseRollout'
import { ReleaseRolloutBar } from './ReleaseRolloutBar'
import { ReleaseStageDot } from './ReleaseStageDot'
import { ReleaseTimelineAxis } from './ReleaseTimelineAxis'
import { ReleaseTimelineSkeleton } from './ReleaseTimelineSkeleton'
import { ReleaseTrackGrid } from './ReleaseTrackGrid'
import { ReleaseTrackLabel } from './ReleaseTrackLabel'
import { ReleaseTrackLane } from './ReleaseTrackLane'
import { ReleaseTrackMarkers } from './ReleaseTrackMarkers'
import {
    CALENDAR_SCALE,
    LANE,
    Lane,
    SPAN_LOOK,
    Track,
    TrackRelated,
    buildTrack,
    mergeOverlapping,
} from './releaseTracks'
import { ReleaseTrackSpan } from './ReleaseTrackSpan'
import { CALENDAR_DAYS_AFTER, ReleaseRow, ReleaseSpan, STAGE_COLOR, STAGE_COLOR_VARS } from './releaseUtils'
import { useInfiniteRows } from './useInfiniteRows'
import { useRefreshChangedFlagHistory } from './useRefreshChangedFlagHistory'
import { useRolloutStepsByFlag } from './useRolloutStepsByFlag'
import { useScrollToToday } from './useScrollToToday'
import { useStickyColumnWidth } from './useStickyColumnWidth'

const NAME = 300
const NAME_NARROW = 148
const NARROW_WIDTH = 640
const SUMMARY = 60
const SUMMARY_OPEN = 36

function TrackHeader({ track, open }: { track: Track; open: boolean }): JSX.Element {
    const { row, lanes } = track
    const { nameWidth } = useContext(CalendarStateContext)
    const narrow = nameWidth < NAME
    return (
        <div className="flex flex-col" style={{ width: nameWidth - 12 }}>
            <div
                className={cn('flex items-center', narrow ? 'gap-1.5' : 'gap-2')}
                style={{ height: open ? SUMMARY_OPEN : SUMMARY }}
            >
                <IconChevronRight
                    className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')}
                />
                <ReleaseStageDot stage={row.stage} />
                <span className={cn('flex min-w-0 flex-1', open && !narrow ? 'items-baseline gap-1.5' : 'flex-col')}>
                    <LinkPrimitive
                        to={urls.release(row.id)}
                        data-attr="release-timeline-release"
                        className="truncate text-xs font-semibold text-foreground hover:underline"
                    >
                        {row.name}
                    </LinkPrimitive>
                    {!(open && narrow) && (
                        <Text size="xs" variant="muted" className="truncate">
                            {row.status}
                        </Text>
                    )}
                </span>
            </div>
            {open &&
                lanes.map((lane) => (
                    <ReleaseTrackLabel key={lane.key} lane={lane} className="border-t border-border/60 pl-5 pr-3" />
                ))}
            {open && !lanes.length && (
                <div className="flex items-center border-t border-border/60 pl-5 pr-3" style={{ height: LANE }}>
                    <Text size="xs" variant="muted">
                        Nothing linked yet
                    </Text>
                </div>
            )}
        </div>
    )
}

function TrackLanesContent({
    track,
    open,
    stickyOffset,
}: {
    track: Track
    open: boolean
    stickyOffset: number
}): JSX.Element {
    const scale = CALENDAR_SCALE()
    const { row, steps, lanes } = track
    const summarySpans = open ? [] : mergeOverlapping(row.spans.filter((span) => span.kind !== 'flag' || !steps.length))
    const hasExperiment = summarySpans.some((span) => span.kind.startsWith('experiment'))
    const laneFor = (span: ReleaseSpan): Lane | undefined =>
        lanes.find((lane) => lane.kind !== 'broadcast' && lane.href === span.href)
    return (
        <div className="relative" style={{ width: scale.days * scale.day }}>
            <ReleaseTrackGrid scale={scale} />
            <div className="relative" style={{ height: open ? SUMMARY_OPEN : SUMMARY }}>
                {steps.length > 0 && !open && (
                    <ReleaseRolloutBar
                        steps={steps}
                        scale={scale}
                        color={STAGE_COLOR[row.stage]}
                        top={26}
                        height={20}
                        stickyOffset={stickyOffset}
                        lane={lanes.find((lane) => lane.kind === 'flag')}
                    />
                )}
                {summarySpans.map((span) =>
                    span.kind === 'early_access' && hasExperiment ? (
                        <ReleaseTrackSpan
                            key={span.key}
                            span={span}
                            scale={scale}
                            top={18}
                            height={6}
                            thin
                            stickyOffset={stickyOffset}
                            lane={laneFor(span)}
                        />
                    ) : (
                        <ReleaseTrackSpan
                            key={span.key}
                            span={span}
                            scale={scale}
                            top={SPAN_LOOK[span.kind].top}
                            height={SPAN_LOOK[span.kind].height}
                            stickyOffset={stickyOffset}
                            lane={laneFor(span)}
                        />
                    )
                )}
                {!open && (
                    <ReleaseTrackMarkers
                        events={row.events.filter(
                            (event) => !(steps.length && event.kind === 'schedule' && event.flagId === row.flags[0]?.id)
                        )}
                        scale={scale}
                        top={3}
                    />
                )}
            </div>
            {open &&
                lanes.map((lane) => (
                    <ReleaseTrackLane
                        key={lane.key}
                        lane={lane}
                        color={STAGE_COLOR[row.stage]}
                        scale={scale}
                        stickyOffset={stickyOffset}
                    />
                ))}
            {open && !lanes.length && <div className="border-t border-border/60" style={{ height: LANE }} />}
        </div>
    )
}

const laneKeys = (track: Track): string => track.lanes.map((lane) => `${lane.key}:${lane.title}`).join('|')

const laneSteps = (track: Track): (RolloutStep[] | undefined)[] =>
    track.lanes.map((lane) => (lane.kind === 'flag' ? lane.steps : undefined))

const TrackLanes = memo(
    TrackLanesContent,
    (previous, next) =>
        previous.open === next.open &&
        previous.stickyOffset === next.stickyOffset &&
        previous.track.row === next.track.row &&
        previous.track.steps === next.track.steps &&
        laneKeys(previous.track) === laneKeys(next.track) &&
        laneSteps(previous.track).every((steps, index) => steps === laneSteps(next.track)[index])
)

interface CalendarState {
    nameWidth: number
    stickyOffset: number
    lastRowId: string | undefined
    sentinel: (node: Element | null) => void
    loadFlagActivity: (flagIds: number[]) => void
    expanded: Record<string, true>
    stepsByFlag: Map<number, RolloutStep[]>
    related: Record<string, TrackRelated>
}

const CalendarStateContext = createContext<CalendarState>({
    nameWidth: NAME,
    stickyOffset: NAME,
    lastRowId: undefined,
    sentinel: () => {},
    loadFlagActivity: () => {},
    expanded: {},
    stepsByFlag: new Map(),
    related: {},
})

function ReleaseCell({ row }: CellContext<ReleaseRow, unknown>): JSX.Element {
    const { expanded, stepsByFlag, related } = useContext(CalendarStateContext)
    return (
        <TrackHeader
            track={buildTrack(row.original, stepsByFlag, related[row.original.id])}
            open={!!expanded[row.original.id]}
        />
    )
}

function TimelineCell({ row }: CellContext<ReleaseRow, unknown>): JSX.Element {
    const { expanded, stepsByFlag, related, lastRowId, sentinel, loadFlagActivity, stickyOffset } =
        useContext(CalendarStateContext)
    const firstFlagId = row.original.flags[0]?.id
    useEffect(() => {
        if (firstFlagId !== undefined) {
            loadFlagActivity([firstFlagId])
        }
    }, [firstFlagId, loadFlagActivity])
    return (
        <>
            <TrackLanes
                track={buildTrack(row.original, stepsByFlag, related[row.original.id])}
                open={!!expanded[row.original.id]}
                stickyOffset={stickyOffset}
            />
            {row.original.id === lastRowId && <div ref={sentinel} />}
        </>
    )
}

function TimelineHeader(): JSX.Element {
    const { stickyOffset } = useContext(CalendarStateContext)
    return <ReleaseTimelineAxis scale={CALENDAR_SCALE()} stickyOffset={stickyOffset} />
}

function calendarColumns(nameWidth: number): ColumnDef<ReleaseRow>[] {
    return [
        {
            id: 'release',
            header: 'Release',
            size: nameWidth,
            enableSorting: false,
            meta: { sticky: 'left' },
            cell: ReleaseCell,
        },
        { id: 'timeline', header: TimelineHeader, enableSorting: false, cell: TimelineCell },
    ]
}

export function ReleaseTimeline(): JSX.Element {
    const { filteredRows, dataLoading, releases, flags } = useValues(releaseLogic)
    const { expanded } = useValues(releaseCalendarLogic)
    const { relatedByRelease } = useValues(releaseRelatedLogic)
    const { toggleExpanded, loadFlagActivity } = useActions(releaseCalendarLogic)

    useEffect(() => {
        const ids = filteredRows.filter((row) => expanded[row.id]).flatMap((row) => row.flags.map((flag) => flag.id))
        if (ids.length) {
            loadFlagActivity(ids)
        }
    }, [expanded, filteredRows, loadFlagActivity])

    const stepsByFlag = useRolloutStepsByFlag(CALENDAR_DAYS_AFTER)

    useRefreshChangedFlagHistory(flags)

    const { visible, sentinel } = useInfiniteRows(filteredRows.length)
    const rows = useMemo(() => filteredRows.slice(0, visible), [filteredRows, visible])
    const lastRowId = visible < filteredRows.length ? rows[rows.length - 1]?.id : undefined
    const [container, setContainer] = useState<HTMLDivElement | null>(null)
    const { width = 0 } = useResizeObserver<HTMLDivElement>({ ref: container })
    const nameWidth = width > 0 && width < NARROW_WIDTH ? NAME_NARROW : NAME
    const stickyOffset = useStickyColumnWidth(container, nameWidth)
    useScrollToToday(container, CALENDAR_SCALE(), true, width > 0 && rows.length > 0)
    const columns = useMemo(() => calendarColumns(nameWidth), [nameWidth])

    const state = useMemo(
        () => ({
            nameWidth,
            stickyOffset,
            lastRowId,
            sentinel,
            loadFlagActivity,
            expanded,
            stepsByFlag,
            related: relatedByRelease,
        }),
        [nameWidth, stickyOffset, lastRowId, sentinel, loadFlagActivity, expanded, stepsByFlag, relatedByRelease]
    )

    return (
        <div
            ref={setContainer}
            className={`overflow-hidden rounded-lg border border-border bg-background ${STAGE_COLOR_VARS} [--quill-table-sticky-bg:var(--background)] [&_td]:py-0 [&_td]:align-top [&_td+td]:p-0 [&_th+th]:p-0`}
            data-attr="release-timeline"
        >
            {dataLoading && !filteredRows.length ? (
                <ReleaseTimelineSkeleton />
            ) : (
                <CalendarStateContext.Provider value={state}>
                    <DataTable
                        columns={columns}
                        data={rows}
                        size="sm"
                        stickyHeader
                        className="max-h-[75vh]"
                        getRowId={(row) => row.id}
                        onRowClick={(row) => toggleExpanded(row.id)}
                        rowClassName={(row) => (expanded[row.id] ? 'bg-fill-hover/40' : undefined)}
                        empty={
                            <Text size="xs" variant="muted">
                                {releases.length
                                    ? 'No release matches these filters.'
                                    : 'No releases yet. Each new feature flag gets one, or create one yourself.'}
                            </Text>
                        }
                    />
                </CalendarStateContext.Provider>
            )}
        </div>
    )
}
