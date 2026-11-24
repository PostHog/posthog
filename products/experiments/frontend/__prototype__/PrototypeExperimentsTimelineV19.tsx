/**
 * Scratch prototype v19: the experiments timeline on the release calendar foundation. Not committed.
 *
 * Reused as is from products/release: the day scale and x(), the axis with sticky month labels and the today mark,
 * the weekend and today grid, the sticky column width hook, the scroll to today math and the DataTable layout.
 * Ported, not imported: the span pill with a sticky label, because ReleaseTrackSpan carries release colors and the
 * release tooltip card, and an experiment bar needs result colors, a halted part and an estimated end.
 */
import type { CellContext, ColumnDef } from '@tanstack/react-table'
import { createContext, useContext, useLayoutEffect, useMemo, useState } from 'react'

import { IconCheck, IconChevronLeft, IconChevronRight, IconPause } from '@posthog/icons'
import { Badge, Button, DataTable, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ReleaseTimelineAxis } from 'products/release/frontend/ReleaseTimelineAxis'
import { ReleaseTrackGrid } from 'products/release/frontend/ReleaseTrackGrid'
import { type Scale, todayScrollLeft, x } from 'products/release/frontend/releaseTracks'
import { useStickyColumnWidth } from 'products/release/frontend/useStickyColumnWidth'

import {
    CONCLUSION_LABEL,
    STATUS_BADGE,
    STATUS_LABEL,
    TIMELINE_GROUP,
    type TimelineGroup,
    type TimelineZoom,
} from './PrototypeExperimentsTimelineV17'
import {
    CONCLUSION,
    type Conclusion,
    LIST_STATUS,
    LIST_TODAY,
    type ListExperiment,
    type ListStatus,
} from './prototypeListData'

/** Days in the visible window for each range. The release calendar has one fixed zoom of 30px a day. */
const ZOOM_DAYS: Record<TimelineZoom, number> = { month: 42, quarter: 119, half: 196 }

const NAME = 264
const NAME_NARROW = 148
const NARROW_WIDTH = 640
const ROW = 48
const GROUP_ROW = 28
const ACTIVITY_ROW = 36
const BAR = 20
/** Below this width a bar is a thin line and its label goes after it, as in ReleaseTrackSpan. */
const NARROW_BAR = 72

function tint(token: string, percent: number): string {
    return `color-mix(in oklab, var(--${token}) ${percent}%, transparent)`
}

/** Base colors per bar state. The release pill mixes its color at 18% and keeps the label in the foreground color. */
const BASE = {
    running: 'data-color-1',
    paused: 'warning-foreground',
    won: 'success-foreground',
    lost: 'destructive-foreground',
    neutral: 'muted-foreground',
} as const

const CONCLUSION_BASE: Record<Conclusion, string> = {
    won: BASE.won,
    lost: BASE.lost,
    inconclusive: BASE.neutral,
    'stopped-early': BASE.paused,
    invalid: BASE.neutral,
}

const HATCH: React.CSSProperties = {
    backgroundImage:
        'repeating-linear-gradient(135deg, color-mix(in oklab, var(--muted-foreground) 35%, transparent) 0 2px, transparent 2px 6px)',
}

const STATUS_ORDER: ListStatus[] = ['running', 'exposure-frozen', 'paused', 'complete', 'draft']

const today = dayjs(LIST_TODAY)

function formatDay(date: string | dayjs.Dayjs): string {
    return dayjs(date).format('MMM D')
}

function scheduleText(experiment: ListExperiment): string {
    if (!experiment.startDate) {
        return `Not launched, created ${formatDay(experiment.createdAt)}`
    }
    const days = dayjs(experiment.endDate ?? today).diff(experiment.startDate, 'day')
    const span = experiment.endDate
        ? `${formatDay(experiment.startDate)} to ${formatDay(experiment.endDate)}`
        : `Since ${formatDay(experiment.startDate)}`
    return `${span} · ${days} days`
}

function barLabel(experiment: ListExperiment): string {
    if (experiment.status === LIST_STATUS.complete) {
        return experiment.conclusion ? CONCLUSION_LABEL[experiment.conclusion] : 'Complete'
    }
    if (experiment.status === LIST_STATUS.running) {
        if (experiment.remainingDays === 0) {
            return 'Target reached'
        }
        return experiment.remainingDays ? `~${experiment.remainingDays} days left` : 'Running'
    }
    return STATUS_LABEL[experiment.status]
}

function barBase(experiment: ListExperiment): string {
    if (experiment.status === LIST_STATUS.complete) {
        return CONCLUSION_BASE[experiment.conclusion ?? CONCLUSION.inconclusive]
    }
    return experiment.status === LIST_STATUS.paused ? BASE.paused : BASE.running
}

/** From a week before the first launch to after the last estimated end, so every bar is in the scale. */
function fullScale(experiments: ListExperiment[], zoom: TimelineZoom, day: number): Scale {
    const starts = experiments.flatMap((experiment) => (experiment.startDate ? [dayjs(experiment.startDate)] : []))
    const ends = experiments.flatMap((experiment) =>
        experiment.status === LIST_STATUS.running && experiment.remainingDays
            ? [today.add(experiment.remainingDays, 'day')]
            : []
    )
    const windowStart = today.subtract(ZOOM_DAYS[zoom], 'day')
    const first = starts.reduce((earliest, date) => (date.isBefore(earliest) ? date : earliest), windowStart)
    const last = ends
        .reduce((latest, date) => (date.isAfter(latest) ? date : latest), today)
        .add(ZOOM_DAYS[zoom] / 2, 'day')
    const start = first.subtract(7, 'day').startOf('month')
    return { start, days: last.diff(start, 'day'), day }
}

type TimelineRow =
    | { kind: 'group'; key: string; label: string; count: number }
    | { kind: 'activity'; key: string }
    | { kind: 'experiment'; key: string; experiment: ListExperiment }

function timelineRows(experiments: ListExperiment[], group: TimelineGroup): TimelineRow[] {
    const byStart = [...experiments].sort((a, b) => (a.startDate ?? '9999').localeCompare(b.startDate ?? '9999'))
    const asRows = (items: ListExperiment[]): TimelineRow[] =>
        items.map((experiment) => ({ kind: 'experiment', key: experiment.key, experiment }))
    const groups =
        group === TIMELINE_GROUP.none
            ? [{ key: 'all', label: '', items: byStart }]
            : group === TIMELINE_GROUP.status
              ? STATUS_ORDER.map((status) => ({
                    key: status,
                    label: STATUS_LABEL[status],
                    items: byStart.filter((experiment) => experiment.status === status),
                }))
              : [...new Set(byStart.map((experiment) => experiment.createdBy))].sort().map((owner) => ({
                    key: owner,
                    label: owner,
                    items: byStart.filter((experiment) => experiment.createdBy === owner),
                }))
    return [
        { kind: 'activity', key: 'activity' },
        ...groups
            .filter((entry) => entry.items.length > 0)
            .flatMap((entry): TimelineRow[] => [
                ...(entry.label
                    ? [
                          {
                              kind: 'group' as const,
                              key: `group-${entry.key}`,
                              label: entry.label,
                              count: entry.items.length,
                          },
                      ]
                    : []),
                ...asRows(entry.items),
            ]),
    ]
}

interface TimelineState {
    scale: Scale
    nameWidth: number
    stickyOffset: number
    group: TimelineGroup
    experiments: ListExperiment[]
    scrollBy: (days: number) => void
    scrollToToday: () => void
}

const TimelineStateContext = createContext<TimelineState | null>(null)

function useTimelineState(): TimelineState {
    const state = useContext(TimelineStateContext)
    if (!state) {
        throw new Error('Timeline cells render inside PrototypeExperimentsTimeline')
    }
    return state
}

function BarTooltip({ experiment }: { experiment: ListExperiment }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <span className="font-medium">{experiment.name}</span>
            <span>{scheduleText(experiment)}</span>
            <span>
                {STATUS_LABEL[experiment.status]}
                {experiment.conclusion ? `, ${CONCLUSION_LABEL[experiment.conclusion].toLowerCase()}` : ''}
                {experiment.haltedAt ? ` since ${formatDay(experiment.haltedAt)}` : ''}
            </span>
            {experiment.status === LIST_STATUS.running && experiment.remainingDays ? (
                <span>{`Estimated end ${formatDay(today.add(experiment.remainingDays, 'day'))}`}</span>
            ) : null}
            {experiment.conclusionComment && <span>{experiment.conclusionComment}</span>}
        </div>
    )
}

/** One pill per experiment, drawn like a release span: soft fill, rounded ends, a label that stays in view on scroll. */
function ExperimentSpan({ experiment }: { experiment: ListExperiment }): JSX.Element | null {
    const { scale, stickyOffset } = useTimelineState()
    if (!experiment.startDate) {
        return (
            <Text
                size="xs"
                variant="muted"
                className="absolute flex items-center pl-2"
                style={{ left: x(today.toISOString(), scale) + scale.day / 2, top: 0, height: ROW }}
            >
                Not launched
            </Text>
        )
    }
    const startDate = experiment.startDate
    const at = (date: string | dayjs.Dayjs): number => x(dayjs(date).toISOString(), scale)
    const solidEnd = experiment.endDate ?? experiment.haltedAt ?? today
    const projectedEnd =
        experiment.status === LIST_STATUS.running && experiment.remainingDays
            ? today.add(experiment.remainingDays, 'day')
            : null
    const end = projectedEnd ?? (experiment.haltedAt ? today : dayjs(solidEnd))
    const left = at(startDate)
    const width = Math.max(at(end) + scale.day / 2 - left, scale.day)
    const solidWidth = Math.min(Math.max(at(solidEnd) + scale.day / 2 - left, scale.day), width)
    const haltedWidth = experiment.haltedAt ? at(today) + scale.day / 2 - left - solidWidth : 0
    const base = barBase(experiment)
    const compact = width < NARROW_BAR
    const targetReached = experiment.status === LIST_STATUS.running && experiment.remainingDays === 0
    const label = (
        <>
            {targetReached && <IconCheck className="text-success-foreground" />}
            {experiment.status === LIST_STATUS.paused && <IconPause />}
            {barLabel(experiment)}
        </>
    )
    return (
        <Tooltip trackCursorAxis="x">
            <TooltipTrigger
                render={
                    <LinkPrimitive
                        to="#"
                        onClick={(event) => event.preventDefault()}
                        aria-label={`${experiment.name}, ${scheduleText(experiment)}`}
                        data-attr="timeline-bar"
                        className="group absolute flex rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        style={{ left, width, top: (ROW - BAR) / 2, height: BAR }}
                    />
                }
            >
                <span
                    className={cn(
                        'relative flex w-full rounded-full group-hover:brightness-105',
                        compact ? 'my-auto h-1.5' : 'h-full'
                    )}
                    style={{ background: tint(base, compact ? 70 : 18), clipPath: 'inset(0 round 9999px)' }}
                >
                    {haltedWidth > 0 && (
                        <span
                            className="absolute inset-y-0"
                            style={{ left: solidWidth, width: haltedWidth, ...HATCH }}
                        />
                    )}
                    {projectedEnd && (
                        <span
                            className="absolute inset-y-0 right-0 rounded-r-full border border-l-0 border-dashed"
                            style={{
                                left: solidWidth,
                                borderColor: tint(base, 70),
                                background: 'var(--card)',
                            }}
                        />
                    )}
                    {!compact && (
                        <span
                            className="sticky flex items-center gap-1 truncate px-2 text-[11px] font-medium text-foreground [&_svg]:size-3"
                            style={{ left: stickyOffset + 8, maxWidth: width - 16 }}
                        >
                            {label}
                        </span>
                    )}
                </span>
                {compact && (
                    <span className="pointer-events-none absolute left-full top-1/2 ml-1.5 flex -translate-y-1/2 items-center gap-1 whitespace-nowrap text-[11px] font-medium text-muted-foreground [&_svg]:size-3">
                        {label}
                    </span>
                )}
            </TooltipTrigger>
            <TooltipContent side="top" align="start">
                <BarTooltip experiment={experiment} />
            </TooltipContent>
        </Tooltip>
    )
}

/** How many experiments ran on each day, one column per day on the shared scale. */
function ActivityBars(): JSX.Element {
    const { scale, experiments } = useTimelineState()
    const counts = Array.from({ length: scale.days }, (_, index) => {
        const date = scale.start.add(index, 'day')
        if (date.isAfter(today)) {
            return 0
        }
        return experiments.filter((experiment) => {
            if (!experiment.startDate || date.isBefore(experiment.startDate)) {
                return false
            }
            const stop = experiment.endDate ?? experiment.haltedAt
            return !stop || !date.isAfter(stop)
        }).length
    })
    const peak = Math.max(1, ...counts)
    return (
        <div className="absolute inset-x-0 bottom-0 top-1.5" aria-label="Experiments running each day">
            {counts.map((count, index) =>
                count ? (
                    <div
                        key={index}
                        title={`${formatDay(scale.start.add(index, 'day'))}: ${count} running`}
                        className="absolute bottom-0 rounded-t-[1px]"
                        style={{
                            left: index * scale.day + 0.5,
                            width: Math.max(scale.day - 1, 1),
                            height: `${(count / peak) * 100}%`,
                            background: tint(BASE.neutral, 40),
                        }}
                    />
                ) : null
            )}
        </div>
    )
}

/** Below this day width the release grid's weekend shading turns into stripes, so wide ranges draw month lines. */
const WEEKEND_MIN_DAY = 12

function MonthGrid({ scale }: { scale: Scale }): JSX.Element {
    const end = scale.start.add(scale.days, 'day')
    const months: number[] = []
    for (let month = scale.start.add(1, 'month').startOf('month'); month.isBefore(end); month = month.add(1, 'month')) {
        months.push(month.diff(scale.start, 'day') * scale.day)
    }
    return (
        <div className="pointer-events-none absolute inset-0">
            {months.map((left) => (
                <div key={left} className="absolute inset-y-0 w-px bg-border/60" style={{ left }} />
            ))}
            <div
                className="absolute inset-y-0 w-px bg-primary"
                style={{ left: x(today.toISOString(), scale) + scale.day / 2 }}
            />
        </div>
    )
}

function rowHeight(row: TimelineRow): number {
    return row.kind === 'group' ? GROUP_ROW : row.kind === 'activity' ? ACTIVITY_ROW : ROW
}

function NameHeader(): JSX.Element {
    const { scrollBy, scrollToToday } = useTimelineState()
    return (
        <div className="flex h-12 items-end justify-between gap-1 pb-1.5 normal-case tracking-normal">
            <Text size="xs" variant="muted">
                Experiment
            </Text>
            <span className="flex items-center gap-0.5">
                <Button
                    size="icon-xs"
                    aria-label="Earlier"
                    tooltip="Earlier"
                    onClick={() => scrollBy(-1)}
                    data-attr="timeline-earlier"
                >
                    <IconChevronLeft />
                </Button>
                <Button size="xs" onClick={scrollToToday} data-attr="timeline-today">
                    Today
                </Button>
                <Button
                    size="icon-xs"
                    aria-label="Later"
                    tooltip="Later"
                    onClick={() => scrollBy(1)}
                    data-attr="timeline-later"
                >
                    <IconChevronRight />
                </Button>
            </span>
        </div>
    )
}

function NameCell({ row }: CellContext<TimelineRow, unknown>): JSX.Element {
    const { nameWidth, group } = useTimelineState()
    const item = row.original
    const style = { width: nameWidth - 24, height: rowHeight(item) }
    if (item.kind === 'activity') {
        return (
            <div className="flex items-center" style={style}>
                <Text size="xs" variant="muted">
                    Running each day
                </Text>
            </div>
        )
    }
    if (item.kind === 'group') {
        return (
            <div className="flex items-center gap-2" style={style}>
                <Text size="xs" weight="medium">
                    {item.label}
                </Text>
                <Text size="xs" variant="muted">
                    {item.count}
                </Text>
            </div>
        )
    }
    const { experiment } = item
    return (
        <div className="flex min-w-0 flex-col justify-center" style={style}>
            <LinkPrimitive
                to="#"
                onClick={(event) => event.preventDefault()}
                className="truncate text-xs font-medium text-foreground hover:underline"
                title={experiment.name}
            >
                {experiment.name}
            </LinkPrimitive>
            <div className="flex min-w-0 items-center gap-1.5">
                {group !== TIMELINE_GROUP.status && (
                    <Badge variant={STATUS_BADGE[experiment.status]} className="shrink-0">
                        {STATUS_LABEL[experiment.status]}
                    </Badge>
                )}
                <Text size="xs" variant="muted" className="truncate">
                    {scheduleText(experiment)}
                </Text>
            </div>
        </div>
    )
}

function TimelineCell({ row }: CellContext<TimelineRow, unknown>): JSX.Element {
    const { scale } = useTimelineState()
    const item = row.original
    return (
        <div className="relative" style={{ width: scale.days * scale.day, height: rowHeight(item) }}>
            {item.kind !== 'group' &&
                (scale.day >= WEEKEND_MIN_DAY ? <ReleaseTrackGrid scale={scale} /> : <MonthGrid scale={scale} />)}
            {item.kind === 'activity' && <ActivityBars />}
            {item.kind === 'experiment' && <ExperimentSpan experiment={item.experiment} />}
        </div>
    )
}

function TimelineHeader(): JSX.Element {
    const { scale, stickyOffset } = useTimelineState()
    return <ReleaseTimelineAxis scale={scale} stickyOffset={stickyOffset} />
}

function timelineColumns(nameWidth: number): ColumnDef<TimelineRow>[] {
    return [
        {
            id: 'experiment',
            header: NameHeader,
            size: nameWidth,
            enableSorting: false,
            meta: { sticky: 'left' },
            cell: NameCell,
        },
        { id: 'timeline', header: TimelineHeader, enableSorting: false, cell: TimelineCell },
    ]
}

function Legend({ swatchStyle, label }: { swatchStyle: React.CSSProperties; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-full" style={swatchStyle} />
            <Text size="xs" variant="muted">
                {label}
            </Text>
        </span>
    )
}

export function PrototypeExperimentsTimeline({
    experiments,
    zoom,
    group,
    scrollToDate,
}: {
    experiments: ListExperiment[]
    zoom: TimelineZoom
    group: TimelineGroup
    /** Opens the timeline with this day at the left edge instead of the default place around today. */
    scrollToDate?: string
}): JSX.Element {
    const [container, setContainer] = useState<HTMLDivElement | null>(null)
    const { width = 0 } = useResizeObserver<HTMLDivElement>({ ref: container })
    const nameWidth = width > 0 && width < NARROW_WIDTH ? NAME_NARROW : NAME
    const stickyOffset = useStickyColumnWidth(container, nameWidth)
    const day = width > stickyOffset ? (width - stickyOffset) / ZOOM_DAYS[zoom] : 30
    const scale = useMemo(() => fullScale(experiments, zoom, day), [experiments, zoom, day])
    const rows = useMemo(() => timelineRows(experiments, group), [experiments, group])
    const columns = useMemo(() => timelineColumns(nameWidth), [nameWidth])

    const viewport = (): HTMLElement | null | undefined =>
        container?.querySelector<HTMLElement>('[data-slot=table-viewport]')
    const todayLeft = (): number => todayScrollLeft(scale, viewport()?.clientWidth ?? 0, stickyOffset, today) ?? 0
    /** The release calendar scrolls to today once; here a range change also puts today back in view. */
    useLayoutEffect(() => {
        const element = viewport()
        if (!element || width === 0) {
            return
        }
        element.scrollLeft = scrollToDate ? x(dayjs(scrollToDate).toISOString(), scale) : todayLeft()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [zoom, width > 0, scrollToDate, stickyOffset])

    const state = useMemo(
        (): TimelineState => ({
            scale,
            nameWidth,
            stickyOffset,
            group,
            experiments,
            scrollBy: (direction) =>
                viewport()?.scrollBy({ left: (direction * ZOOM_DAYS[zoom] * scale.day) / 2, behavior: 'smooth' }),
            scrollToToday: () => viewport()?.scrollTo({ left: todayLeft(), behavior: 'smooth' }),
        }),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [scale, nameWidth, stickyOffset, group, experiments, zoom, container]
    )

    return (
        <div
            className="flex flex-col overflow-hidden rounded-lg border border-border bg-card"
            data-attr="experiments-timeline"
        >
            <div
                ref={setContainer}
                className="[--quill-table-sticky-bg:var(--card)] [&_td]:py-0 [&_td]:align-top [&_td+td]:p-0 [&_th+th]:p-0"
                data-attr="timeline-scroller"
            >
                <TimelineStateContext.Provider value={state}>
                    <DataTable
                        columns={columns}
                        data={rows}
                        size="sm"
                        stickyHeader
                        className="max-h-[70vh]"
                        getRowId={(row) => row.key}
                        rowClassName={(row) => (row.kind === 'group' ? 'bg-fill-hover' : undefined)}
                        empty={
                            <Text size="xs" variant="muted">
                                No experiment matches these filters.
                            </Text>
                        }
                    />
                </TimelineStateContext.Provider>
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-3 py-2">
                <Legend label="Running" swatchStyle={{ background: tint(BASE.running, 18) }} />
                <Legend
                    label="Estimated running time"
                    swatchStyle={{ border: `1px dashed ${tint(BASE.running, 70)}` }}
                />
                <Legend
                    label="Paused or exposure frozen"
                    swatchStyle={{ ...HATCH, background: tint(BASE.paused, 18) }}
                />
                <Legend label="Won" swatchStyle={{ background: tint(BASE.won, 18) }} />
                <Legend label="Lost" swatchStyle={{ background: tint(BASE.lost, 18) }} />
                <Legend label="Inconclusive" swatchStyle={{ background: tint(BASE.neutral, 18) }} />
                <Legend label="Stopped early" swatchStyle={{ background: tint(BASE.paused, 18) }} />
                <Text size="xs" variant="muted" className="ml-auto">
                    Scroll sideways or use the arrows to see earlier experiments
                </Text>
            </div>
        </div>
    )
}
