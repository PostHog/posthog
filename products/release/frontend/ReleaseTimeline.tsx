import { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { DataTable, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { releaseLogic } from './releaseLogic'
import { RolloutStep, rolloutSteps } from './releaseRollout'
import { ReleaseRolloutChart } from './ReleaseRolloutChart'
import { ReleaseStageDot } from './ReleaseStageDot'
import {
    CALENDAR_DAYS_AFTER,
    CALENDAR_DAYS_BEFORE,
    ReleaseEvent,
    ReleaseRow,
    ReleaseSpan,
    STAGE_COLOR,
    STAGE_COLOR_VARS,
} from './releaseUtils'

const DAY = 30
const BEFORE = CALENDAR_DAYS_BEFORE
const AFTER = CALENDAR_DAYS_AFTER
const TOTAL = BEFORE + AFTER
const NAME = 300
const SUMMARY = 60
const SUMMARY_OPEN = 36
const LANE = 34
const FLAG_LANE = 52
const MARKER_LABEL_WIDTH = 176
const MARKER_GUTTER = 28
const MIN_MARKER_LABEL = 24
const NARROW = 72
const ACTIVITY_ROWS = 40
const PAGE_SIZE = 50

const SPAN_LOOK: Record<ReleaseSpan['kind'], { top: number; height: number; color: string }> = {
    flag: { top: 30, height: 14, color: STAGE_COLOR.flag },
    early_access: { top: 4, height: 14, color: STAGE_COLOR.early_access },
    experiment: { top: 4, height: 14, color: STAGE_COLOR.experiment },
    experiment_done: { top: 4, height: 14, color: STAGE_COLOR.ended },
}

const TONE_COLOR: Record<NonNullable<ReleaseSpan['tone']>, string> = {
    default: STAGE_COLOR.ended,
    info: STAGE_COLOR.experiment,
    warning: STAGE_COLOR.early_access,
    success: STAGE_COLOR.released,
}

interface Scale {
    start: dayjs.Dayjs
    days: number
    day: number
}

const CALENDAR_SCALE = (): Scale => ({ start: dayjs().startOf('day').subtract(BEFORE, 'day'), days: TOTAL, day: DAY })

function x(date: string, scale: Scale): number {
    return Math.max(0, Math.min(scale.days, dayjs(date).startOf('day').diff(scale.start, 'day'))) * scale.day
}

type Lane =
    | {
          key: string
          kind: 'flag'
          title: string
          status: string
          live: boolean
          steps: RolloutStep[]
          href: string
      }
    | {
          key: string
          kind: 'experiment' | 'early_access'
          title: string
          status: string
          live: boolean
          span: ReleaseSpan | null
          href: string
      }
    | {
          key: string
          kind: 'broadcast'
          title: string
          status: string
          live: boolean
          events: ReleaseEvent[]
          href: string
      }

interface Track {
    row: ReleaseRow
    steps: RolloutStep[]
    lanes: Lane[]
}

function buildTrack(row: ReleaseRow, stepsByFlag: Map<number, RolloutStep[]>): Track {
    const lanes: Lane[] = []
    for (const flag of row.flags) {
        lanes.push({
            key: `flag-${flag.id}`,
            kind: 'flag',
            title: flag.key,
            status: flag.active ? 'Live' : 'Off',
            live: !!flag.active,
            steps: stepsByFlag.get(flag.id) ?? [],
            href: urls.featureFlag(flag.id),
        })
    }
    for (const experiment of row.experiments) {
        const span = row.spans.find((item) => item.href === urls.experiment(experiment.id)) ?? null
        lanes.push({
            key: `experiment-${experiment.id}`,
            kind: 'experiment',
            title: experiment.name,
            status: experiment.end_date ? 'Complete' : experiment.start_date ? 'Running' : 'Draft',
            live: !!experiment.start_date && !experiment.end_date,
            span,
            href: urls.experiment(experiment.id),
        })
    }
    for (const item of row.earlyAccess) {
        lanes.push({
            key: `early-access-${item.id}`,
            kind: 'early_access',
            title: item.name,
            status: item.stage,
            live: ['alpha', 'beta', 'general-availability'].includes(item.stage),
            span: row.spans.find((span) => span.key === `ea-${item.id}`) ?? null,
            href: urls.earlyAccessFeature(item.id),
        })
    }
    for (const broadcast of row.broadcasts) {
        lanes.push({
            key: `broadcast-${broadcast.id}`,
            kind: 'broadcast',
            title: broadcast.name || 'Untitled broadcast',
            status: broadcast.status,
            live: broadcast.status === 'active',
            events: row.events.filter(
                (event) => event.kind === 'broadcast' && event.href === urls.broadcast(broadcast.id)
            ),
            href: urls.broadcast(broadcast.id),
        })
    }
    return { row, steps: row.flags[0] ? (stepsByFlag.get(row.flags[0].id) ?? []) : [], lanes }
}

function sendLabel(event: ReleaseEvent): string {
    const kind = event.title.split(':')[0].replace('Broadcast', '').trim()
    return event.upcoming ? 'Scheduled' : kind ? kind[0].toUpperCase() + kind.slice(1) : 'Sent'
}

function laneHeight(lane: Lane): number {
    return lane.kind === 'flag' ? FLAG_LANE : LANE
}

const LANE_ICON: Record<Lane['kind'], string> = {
    flag: 'feature_flag',
    experiment: 'experiment',
    early_access: 'early_access_feature',
    broadcast: 'broadcasts',
}

function statusLabel(status: string): string {
    return status.charAt(0).toUpperCase() + status.slice(1).replace('-', ' ')
}

function LaneLabel({ lane, className }: { lane: Lane; className?: string }): JSX.Element {
    return (
        <div className={cn('flex items-center gap-2', className)} style={{ height: laneHeight(lane) }}>
            <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-3.5">
                {iconForType(LANE_ICON[lane.kind] as never)}
            </span>
            <LinkPrimitive
                to={lane.href}
                className={cn(
                    'min-w-0 flex-1 truncate text-foreground hover:underline',
                    lane.kind === 'flag' ? 'font-mono text-[11px]' : 'text-xs'
                )}
            >
                {lane.title}
            </LinkPrimitive>
            {!lane.live && (
                <Text size="xs" variant="muted" className="shrink-0">
                    {statusLabel(lane.status)}
                </Text>
            )}
        </div>
    )
}

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
                    <LaneLabel key={lane.key} lane={lane} className="border-t border-border/60 pl-5 pr-3" />
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

function Grid({ scale }: { scale: Scale }): JSX.Element {
    const { start, days, day: width } = scale
    const today = dayjs().startOf('day')
    return (
        <div className="pointer-events-none absolute inset-0">
            {Array.from({ length: days }, (_, index) => start.add(index, 'day')).map((day, index) =>
                day.day() === 0 || day.day() === 6 ? (
                    <div
                        key={index}
                        className="absolute inset-y-0 bg-fill-hover opacity-60"
                        style={{ left: index * width, width }}
                    />
                ) : null
            )}
            <div
                className="absolute inset-y-0 w-px bg-primary"
                style={{ left: today.diff(start, 'day') * width + width / 2 }}
            />
        </div>
    )
}

function Markers({ events, scale, top }: { events: ReleaseEvent[]; scale: Scale; top: number }): JSX.Element {
    const { start } = scale
    const end = start.add(scale.days, 'day')
    const shown = events
        .filter(
            (event) =>
                (event.upcoming || event.kind === 'broadcast') &&
                !dayjs(event.date).isBefore(start) &&
                dayjs(event.date).isBefore(end)
        )
        .sort((a, b) => a.date.localeCompare(b.date))
    return (
        <>
            {shown.map((event, index) => {
                const next = shown[index + 1]
                const room = next ? x(next.date, scale) - x(event.date, scale) - MARKER_GUTTER : MARKER_LABEL_WIDTH
                return (
                    <div
                        key={event.key}
                        title={`${dayjs(event.date).format('D MMM')}: ${event.title}${event.detail ? ` (${event.detail})` : ''}`}
                        className="absolute flex h-4 items-center gap-1 whitespace-nowrap text-[11px] font-medium text-muted-foreground"
                        style={{ left: x(event.date, scale) + scale.day / 2 - 6, top }}
                        data-attr="release-timeline-marker"
                    >
                        {event.kind === 'broadcast' ? (
                            <span className="flex size-4 items-center justify-center rounded-sm bg-background text-foreground [&_svg]:size-3">
                                {iconForType('broadcasts')}
                            </span>
                        ) : (
                            <span className="size-2.5 rotate-45 border-2 border-primary bg-background" />
                        )}
                        {room >= MIN_MARKER_LABEL && (
                            <span className="truncate" style={{ maxWidth: Math.min(room, MARKER_LABEL_WIDTH) }}>
                                {event.kind === 'broadcast' ? event.title.split(':')[0] : event.title}
                            </span>
                        )}
                    </div>
                )
            })}
        </>
    )
}

function SpanBar({
    span,
    scale,
    top,
    height,
}: {
    span: ReleaseSpan
    scale: Scale
    top: number
    height: number
}): JSX.Element | null {
    const left = x(span.from, scale)
    const width = Math.max(x(span.to, scale) + scale.day / 2 - left, scale.day)
    if (x(span.to, scale) === 0) {
        return null
    }
    const color = span.tone ? TONE_COLOR[span.tone] : SPAN_LOOK[span.kind].color
    return (
        <div className="absolute flex" style={{ left, width, top, height }}>
            <div
                className={cn('flex w-full overflow-hidden rounded-full', width < NARROW ? 'my-auto h-1.5' : 'h-full')}
                style={{
                    backgroundColor: `color-mix(in oklab, ${color} ${width < NARROW ? 70 : 18}%, transparent)`,
                }}
            >
                <LinkPrimitive
                    to={span.href}
                    title={span.label}
                    className="flex w-full items-center px-2 text-[10px] font-medium text-foreground"
                >
                    {width >= NARROW && <span className="truncate">{span.label}</span>}
                </LinkPrimitive>
            </div>
            {width < NARROW && span.label && (
                <span className="pointer-events-none absolute left-full top-1/2 ml-1.5 -translate-y-1/2 whitespace-nowrap text-[10px] font-medium text-muted-foreground">
                    {span.label}
                </span>
            )}
        </div>
    )
}

function mergeOverlapping(spans: ReleaseSpan[]): ReleaseSpan[] {
    const merged: (ReleaseSpan & { count: number })[] = []
    for (const span of [...spans].sort((a, b) => a.from.localeCompare(b.from))) {
        const top = SPAN_LOOK[span.kind].top
        const previous = merged.find(
            (item) => SPAN_LOOK[item.kind].top === top && !dayjs(span.from).isAfter(dayjs(item.to), 'day')
        )
        if (!previous) {
            merged.push({ ...span, count: 1 })
            continue
        }
        previous.count += 1
        previous.to = dayjs(span.to).isAfter(dayjs(previous.to)) ? span.to : previous.to
        if (span.kind === 'experiment') {
            previous.kind = 'experiment'
            previous.tone = span.tone
        }
        previous.label = span.kind.startsWith('experiment')
            ? `${previous.count} experiments`
            : `${previous.label?.split(' +')[0] ?? ''} +${previous.count - 1}`
    }
    return merged
}

function LaneTrack({ lane, color, scale }: { lane: Lane; color: string; scale: Scale }): JSX.Element {
    const height = laneHeight(lane)
    return (
        <div className="relative border-t border-border/60" style={{ height }}>
            {lane.kind === 'flag' ? (
                <ReleaseRolloutChart
                    color={color}
                    steps={lane.steps}
                    start={scale.start}
                    days={scale.days}
                    dayWidth={scale.day}
                    height={FLAG_LANE}
                    labelRoom={18}
                    className="!absolute left-0 top-0"
                />
            ) : lane.kind === 'broadcast' ? (
                <Markers
                    events={lane.events.map((event) => ({ ...event, title: sendLabel(event) }))}
                    scale={scale}
                    top={(height - 16) / 2}
                />
            ) : lane.span ? (
                <SpanBar span={lane.span} scale={scale} top={(height - 18) / 2} height={18} />
            ) : null}
        </div>
    )
}

function TrackLanes({ track, open }: { track: Track; open: boolean }): JSX.Element {
    const scale = CALENDAR_SCALE()
    const { row, steps, lanes } = track
    const summarySpans = open ? [] : mergeOverlapping(row.spans.filter((span) => span.kind !== 'flag' || !steps.length))
    return (
        <div className="relative" style={{ width: scale.days * scale.day }}>
            <Grid scale={scale} />
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
                {summarySpans.map((span) => (
                    <SpanBar
                        key={span.key}
                        span={span}
                        scale={scale}
                        top={SPAN_LOOK[span.kind].top}
                        height={SPAN_LOOK[span.kind].height}
                    />
                ))}
                {!open && (
                    <Markers
                        events={row.events.filter((event) => !(steps.length && event.kind === 'schedule'))}
                        scale={scale}
                        top={3}
                    />
                )}
            </div>
            {open &&
                lanes.map((lane) => (
                    <LaneTrack key={lane.key} lane={lane} color={STAGE_COLOR[row.stage]} scale={scale} />
                ))}
            {open && !lanes.length && <div className="border-t border-border/60" style={{ height: LANE }} />}
        </div>
    )
}

function TimelineAxis({ scale }: { scale: Scale }): JSX.Element {
    const { start, day: width } = scale
    const today = dayjs().startOf('day')
    const days = Array.from({ length: scale.days }, (_, index) => start.add(index, 'day'))
    const months = days.filter((day, index) => day.date() === 1 || (index === 0 && day.daysInMonth() - day.date() >= 4))
    return (
        <div className="relative h-12" style={{ width: scale.days * width }}>
            {months.map((month) => (
                <div
                    key={month.format('YYYY-MM-DD')}
                    className="absolute top-1.5 pl-2 text-[11px] font-semibold normal-case tracking-normal text-foreground"
                    style={{ left: month.diff(start, 'day') * width }}
                >
                    {month.format('MMMM YYYY')}
                </div>
            ))}
            {days.map((day, index) =>
                width >= 22 || day.day() === 1 || day.isSame(today, 'day') ? (
                    <div
                        key={index}
                        className="absolute bottom-1.5 flex justify-center text-[11px] font-medium normal-case leading-5 tracking-normal tabular-nums"
                        style={{ left: index * width + width / 2 - 15, width: 30 }}
                    >
                        {day.isSame(today, 'day') ? (
                            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 font-semibold text-primary-foreground">
                                {day.date()}
                            </span>
                        ) : (
                            <span
                                className={
                                    day.day() === 0 || day.day() === 6
                                        ? 'text-muted-foreground opacity-60'
                                        : 'text-muted-foreground'
                                }
                            >
                                {day.date()}
                            </span>
                        )}
                    </div>
                ) : null
            )}
        </div>
    )
}

export function ReleaseTimeline(): JSX.Element {
    const { filteredRows, dataLoading, releases, flags, scheduledChanges } = useValues(releaseLogic)
    const { expanded, flagActivity } = useValues(releaseCalendarLogic)
    const { toggleExpanded, loadFlagActivity } = useActions(releaseCalendarLogic)

    useEffect(() => {
        const ids = [
            ...new Set(filteredRows.slice(0, ACTIVITY_ROWS).flatMap((row) => row.flags.map((flag) => flag.id))),
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

    const tracks = useMemo(() => {
        const today = dayjs()
        const horizon = CALENDAR_SCALE().start.add(TOTAL, 'day')
        const stepsByFlag = new Map<number, RolloutStep[]>()
        for (const flag of flags) {
            if (flagActivity[flag.id]) {
                stepsByFlag.set(flag.id, rolloutSteps(flag, flagActivity[flag.id], scheduledChanges, today, horizon))
            }
        }
        return filteredRows.map((row) => buildTrack(row, stepsByFlag))
    }, [filteredRows, flags, flagActivity, scheduledChanges])

    const columns = useMemo<ColumnDef<Track>[]>(
        () => [
            {
                id: 'release',
                header: 'Release',
                size: NAME,
                enableSorting: false,
                meta: { sticky: 'left' },
                cell: ({ row }) => <TrackHeader track={row.original} open={!!expanded[row.original.row.id]} />,
            },
            {
                id: 'timeline',
                header: () => <TimelineAxis scale={CALENDAR_SCALE()} />,
                enableSorting: false,
                cell: ({ row }) => <TrackLanes track={row.original} open={!!expanded[row.original.row.id]} />,
            },
        ],
        [expanded]
    )

    return (
        <div
            className={`overflow-hidden rounded-lg border border-border bg-background ${STAGE_COLOR_VARS} [--quill-table-sticky-bg:var(--background)] [&_td]:py-0 [&_td]:align-top [&_td+td]:p-0 [&_th+th]:p-0`}
            data-attr="release-timeline"
        >
            <DataTable
                columns={columns}
                data={tracks}
                size="sm"
                stickyHeader
                pageSize={tracks.length > PAGE_SIZE ? PAGE_SIZE : undefined}
                getRowId={(track) => track.row.id}
                onRowClick={(track) => toggleExpanded(track.row.id)}
                rowClassName={(track) => (expanded[track.row.id] ? 'bg-fill-hover/40' : undefined)}
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
        </div>
    )
}
