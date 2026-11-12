import { CellContext, ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { createContext, useContext, useEffect, useMemo } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { DataTable, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { releaseLogic } from './releaseLogic'
import { RolloutStep, rolloutSteps } from './releaseRollout'
import { ReleaseRolloutChart } from './ReleaseRolloutChart'
import { ReleaseStageDot } from './ReleaseStageDot'
import { ReleaseTimelineAxis } from './ReleaseTimelineAxis'
import { ReleaseTrackGrid } from './ReleaseTrackGrid'
import { ReleaseTrackLabel } from './ReleaseTrackLabel'
import { ReleaseTrackLane } from './ReleaseTrackLane'
import { ReleaseTrackMarkers } from './ReleaseTrackMarkers'
import { CALENDAR_SCALE, LANE, SPAN_LOOK, TOTAL, Track, buildTrack, mergeOverlapping } from './releaseTracks'
import { ReleaseTrackSpan } from './ReleaseTrackSpan'
import { ReleaseRow, STAGE_COLOR, STAGE_COLOR_VARS } from './releaseUtils'

const NAME = 300
const SUMMARY = 60
const SUMMARY_OPEN = 36
const ACTIVITY_ROWS = 40
const PAGE_SIZE = 50

function TrackHeader({ track, open }: { track: Track; open: boolean }): JSX.Element {
    const { row, lanes } = track
    return (
        <div className="flex flex-col" style={{ width: NAME - 12 }}>
            <div className="flex items-center gap-2" style={{ height: open ? SUMMARY_OPEN : SUMMARY }}>
                <IconChevronRight
                    className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')}
                />
                <ReleaseStageDot stage={row.stage} />
                <span className={cn('flex min-w-0 flex-1', open ? 'items-baseline gap-1.5' : 'flex-col')}>
                    <LinkPrimitive
                        to={urls.release(row.id)}
                        data-attr="release-timeline-release"
                        className="truncate text-xs font-semibold text-foreground hover:underline"
                    >
                        {row.name}
                    </LinkPrimitive>
                    <Text size="xs" variant="muted" className="truncate">
                        {row.status}
                    </Text>
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

function TrackLanes({ track, open }: { track: Track; open: boolean }): JSX.Element {
    const scale = CALENDAR_SCALE()
    const { row, steps, lanes } = track
    const summarySpans = open ? [] : mergeOverlapping(row.spans.filter((span) => span.kind !== 'flag' || !steps.length))
    const hasExperiment = summarySpans.some((span) => span.kind.startsWith('experiment'))
    return (
        <div className="relative" style={{ width: scale.days * scale.day }}>
            <ReleaseTrackGrid scale={scale} />
            <div className="relative" style={{ height: open ? SUMMARY_OPEN : SUMMARY }}>
                {steps.length > 0 && !open && (
                    <ReleaseRolloutChart
                        color={STAGE_COLOR[row.stage]}
                        steps={steps}
                        start={scale.start}
                        days={scale.days}
                        dayWidth={scale.day}
                        height={38}
                        labelRoom={13}
                        note={
                            row.flags.length > 1
                                ? `+${row.flags.length - 1} ${row.flags.length === 2 ? 'flag' : 'flags'}`
                                : undefined
                        }
                        className="!absolute left-0"
                        style={{ top: 20 }}
                    />
                )}
                {summarySpans.map((span) =>
                    span.kind === 'early_access' && hasExperiment ? (
                        <ReleaseTrackSpan key={span.key} span={span} scale={scale} top={18} height={6} thin />
                    ) : (
                        <ReleaseTrackSpan
                            key={span.key}
                            span={span}
                            scale={scale}
                            top={SPAN_LOOK[span.kind].top}
                            height={SPAN_LOOK[span.kind].height}
                        />
                    )
                )}
                {!open && (
                    <ReleaseTrackMarkers
                        events={row.events.filter(
                            (event) =>
                                !(
                                    steps.length &&
                                    event.kind === 'schedule' &&
                                    event.href === urls.featureFlag(row.flags[0]?.id)
                                )
                        )}
                        scale={scale}
                        top={3}
                    />
                )}
            </div>
            {open &&
                lanes.map((lane) => (
                    <ReleaseTrackLane key={lane.key} lane={lane} color={STAGE_COLOR[row.stage]} scale={scale} />
                ))}
            {open && !lanes.length && <div className="border-t border-border/60" style={{ height: LANE }} />}
        </div>
    )
}

interface CalendarState {
    expanded: Record<string, true>
    stepsByFlag: Map<number, RolloutStep[]>
}

const CalendarStateContext = createContext<CalendarState>({ expanded: {}, stepsByFlag: new Map() })

function ReleaseCell({ row }: CellContext<ReleaseRow, unknown>): JSX.Element {
    const { expanded, stepsByFlag } = useContext(CalendarStateContext)
    return <TrackHeader track={buildTrack(row.original, stepsByFlag)} open={!!expanded[row.original.id]} />
}

function TimelineCell({ row }: CellContext<ReleaseRow, unknown>): JSX.Element {
    const { expanded, stepsByFlag } = useContext(CalendarStateContext)
    return <TrackLanes track={buildTrack(row.original, stepsByFlag)} open={!!expanded[row.original.id]} />
}

function TimelineHeader(): JSX.Element {
    return <ReleaseTimelineAxis scale={CALENDAR_SCALE()} />
}

const COLUMNS: ColumnDef<ReleaseRow>[] = [
    { id: 'release', header: 'Release', size: NAME, enableSorting: false, meta: { sticky: 'left' }, cell: ReleaseCell },
    { id: 'timeline', header: TimelineHeader, enableSorting: false, cell: TimelineCell },
]

export function ReleaseTimeline(): JSX.Element {
    const { filteredRows, dataLoading, releases, flags, scheduledChanges } = useValues(releaseLogic)
    const { expanded, flagActivity } = useValues(releaseCalendarLogic)
    const { toggleExpanded, loadFlagActivity } = useActions(releaseCalendarLogic)

    useEffect(() => {
        const ids = [
            ...new Set(filteredRows.slice(0, ACTIVITY_ROWS).flatMap((row) => (row.flags[0] ? [row.flags[0].id] : []))),
        ]
        if (ids.length) {
            loadFlagActivity(ids)
        }
    }, [filteredRows, loadFlagActivity])

    useEffect(() => {
        const ids = filteredRows.filter((row) => expanded[row.id]).flatMap((row) => row.flags.map((flag) => flag.id))
        if (ids.length) {
            loadFlagActivity(ids)
        }
    }, [expanded, filteredRows, loadFlagActivity])

    const stepsByFlag = useMemo(() => {
        const today = dayjs()
        const horizon = CALENDAR_SCALE().start.add(TOTAL, 'day')
        const steps = new Map<number, RolloutStep[]>()
        for (const flag of flags) {
            if (flagActivity[flag.id]) {
                steps.set(flag.id, rolloutSteps(flag, flagActivity[flag.id], scheduledChanges, today, horizon))
            }
        }
        return steps
    }, [flags, flagActivity, scheduledChanges])

    const state = useMemo(() => ({ expanded, stepsByFlag }), [expanded, stepsByFlag])

    return (
        <div
            className={`overflow-hidden rounded-lg border border-border bg-background ${STAGE_COLOR_VARS} [--quill-table-sticky-bg:var(--background)] [&_td]:py-0 [&_td]:align-top [&_td+td]:p-0 [&_th+th]:p-0`}
            data-attr="release-timeline"
        >
            <CalendarStateContext.Provider value={state}>
                <DataTable
                    columns={COLUMNS}
                    data={filteredRows}
                    size="sm"
                    stickyHeader
                    className="max-h-[75vh]"
                    pageSize={filteredRows.length > PAGE_SIZE ? PAGE_SIZE : undefined}
                    getRowId={(row) => row.id}
                    onRowClick={(row) => toggleExpanded(row.id)}
                    rowClassName={(row) => (expanded[row.id] ? 'bg-fill-hover/40' : undefined)}
                    empty={
                        <Text size="xs" variant="muted">
                            {dataLoading
                                ? 'Loading releases…'
                                : releases.length
                                  ? 'No release matches these filters.'
                                  : 'No releases yet. Each new feature flag gets one, or create one yourself.'}
                        </Text>
                    }
                />
            </CalendarStateContext.Provider>
        </div>
    )
}
