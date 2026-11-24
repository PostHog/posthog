/** Scratch prototype v17: the timeline scrolls sideways through every experiment; the range control sets the window width. Not committed. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { IconCheck, IconChevronLeft, IconChevronRight, IconPause } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import {
    CONCLUSION,
    type Conclusion,
    LIST_STATUS,
    LIST_TODAY,
    type ListExperiment,
    type ListStatus,
} from './prototypeListData'

export const TIMELINE_ZOOM = { month: 'month', quarter: 'quarter', half: 'half' } as const
export type TimelineZoom = (typeof TIMELINE_ZOOM)[keyof typeof TIMELINE_ZOOM]

export const TIMELINE_GROUP = { none: 'none', status: 'status', owner: 'owner' } as const
export type TimelineGroup = (typeof TIMELINE_GROUP)[keyof typeof TIMELINE_GROUP]

/** Days shown before and after today for each zoom. The future part leaves room for the running time estimates. */
const ZOOM_RANGE: Record<TimelineZoom, { before: number; after: number; label: string }> = {
    month: { before: 28, after: 14, label: '6 weeks' },
    quarter: { before: 91, after: 28, label: '4 months' },
    half: { before: 168, after: 28, label: '7 months' },
}

export const STATUS_LABEL: Record<ListStatus, string> = {
    draft: 'Draft',
    running: 'Running',
    paused: 'Paused',
    'exposure-frozen': 'Exposure frozen',
    complete: 'Complete',
}

export const STATUS_BADGE: Record<ListStatus, 'default' | 'success' | 'warning' | 'info' | 'completed'> = {
    draft: 'default',
    running: 'success',
    paused: 'warning',
    'exposure-frozen': 'info',
    complete: 'completed',
}

export const CONCLUSION_LABEL: Record<Conclusion, string> = {
    won: 'Won',
    lost: 'Lost',
    inconclusive: 'Inconclusive',
    'stopped-early': 'Stopped early',
    invalid: 'Invalid',
}

/** Status and result colors from the quill tokens, mixed inline because the bars need a softer fill than the text color. */
function tint(token: string, percent: number): string {
    return `color-mix(in oklab, var(--${token}) ${percent}%, transparent)`
}

const TONE = {
    running: tint('data-color-1', 65),
    paused: tint('warning-foreground', 65),
    won: tint('success-foreground', 70),
    lost: tint('destructive-foreground', 70),
    neutral: tint('muted-foreground', 45),
    stoppedEarly: tint('warning-foreground', 65),
} as const

const CONCLUSION_TONE: Record<Conclusion, string> = {
    won: TONE.won,
    lost: TONE.lost,
    inconclusive: TONE.neutral,
    'stopped-early': TONE.stoppedEarly,
    invalid: tint('muted-foreground', 25),
}

/** Diagonal stripes for the time an experiment stopped collecting exposures. */
const HATCH: React.CSSProperties = {
    backgroundImage:
        'repeating-linear-gradient(135deg, color-mix(in oklab, var(--muted-foreground) 35%, transparent) 0 2px, transparent 2px 6px)',
}

const STATUS_ORDER: ListStatus[] = ['running', 'exposure-frozen', 'paused', 'complete', 'draft']

const today = dayjs(LIST_TODAY)

function daysFrom(date: string | dayjs.Dayjs, origin: dayjs.Dayjs): number {
    return dayjs(date).diff(origin, 'day')
}

function formatDay(date: string | dayjs.Dayjs): string {
    return dayjs(date).format('MMM D')
}

function runningDays(experiment: ListExperiment): number | null {
    if (!experiment.startDate) {
        return null
    }
    return daysFrom(experiment.endDate ?? today, dayjs(experiment.startDate))
}

/** One line under the name, in words, so the row reads without hovering the bar. */
function scheduleText(experiment: ListExperiment): string {
    if (!experiment.startDate) {
        return `Not launched, created ${formatDay(experiment.createdAt)}`
    }
    const days = runningDays(experiment)
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

interface Range {
    start: dayjs.Dayjs
    days: number
}

function toPercent(date: string | dayjs.Dayjs, range: Range): number {
    return (daysFrom(date, range.start) / range.days) * 100
}

/** Clamps a segment to the visible range. Returns null when the whole segment is outside it. */
function segment(
    from: string | dayjs.Dayjs,
    to: string | dayjs.Dayjs,
    range: Range
): { left: number; width: number; clippedStart: boolean } | null {
    const left = toPercent(from, range)
    const right = toPercent(to, range)
    if (right <= 0 || left >= 100) {
        return null
    }
    const clampedLeft = Math.max(left, 0)
    return { left: clampedLeft, width: Math.max(Math.min(right, 100) - clampedLeft, 0.6), clippedStart: left < 0 }
}

function useTicks(range: Range, zoom: TimelineZoom): { months: { label: string; left: number }[]; lines: number[] } {
    const end = range.start.add(range.days, 'day')
    const months: { label: string; left: number }[] = []
    let month = range.start.startOf('month')
    while (month.isBefore(end)) {
        const left = toPercent(month, range)
        months.push({ label: month.format(zoom === TIMELINE_ZOOM.month ? 'MMMM' : 'MMM'), left: Math.max(left, 0) })
        month = month.add(1, 'month')
    }
    const lines: number[] = []
    if (zoom === TIMELINE_ZOOM.half) {
        months.forEach((tick) => tick.left > 0 && lines.push(tick.left))
    } else {
        let week = range.start.day(1)
        while (week.isBefore(end)) {
            const left = toPercent(week, range)
            if (left > 0) {
                lines.push(left)
            }
            week = week.add(1, 'week')
        }
    }
    return { months, lines }
}

function Gridlines({ lines, todayLeft }: { lines: number[]; todayLeft: number }): JSX.Element {
    return (
        <div aria-hidden className="pointer-events-none absolute inset-0">
            {lines.map((left) => (
                <div key={left} className="absolute inset-y-0 w-px bg-border/60" style={{ left: `${left}%` }} />
            ))}
            <div className="absolute inset-y-0 w-px bg-primary" style={{ left: `${todayLeft}%` }} />
        </div>
    )
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

function ExperimentBar({ experiment, range }: { experiment: ListExperiment; range: Range }): JSX.Element | null {
    if (!experiment.startDate) {
        return (
            <Text
                size="xs"
                variant="muted"
                className="absolute inset-y-0 flex items-center pl-2"
                style={{ left: `${toPercent(today, range)}%` }}
            >
                Not launched
            </Text>
        )
    }
    const solidEnd = experiment.endDate ?? experiment.haltedAt ?? today
    const solid = segment(experiment.startDate, solidEnd, range)
    const halted = experiment.haltedAt ? segment(experiment.haltedAt, today, range) : null
    const projected =
        experiment.status === LIST_STATUS.running && experiment.remainingDays
            ? segment(today, today.add(experiment.remainingDays, 'day'), range)
            : null
    const fill =
        experiment.status === LIST_STATUS.complete
            ? CONCLUSION_TONE[experiment.conclusion ?? CONCLUSION.inconclusive]
            : experiment.status === LIST_STATUS.paused
              ? TONE.paused
              : TONE.running
    const last = projected ?? halted ?? solid
    if (!last) {
        return (
            <Text size="xs" variant="muted" className="absolute inset-y-0 left-0 flex items-center pl-2">
                {`← Ended ${formatDay(solidEnd)}, ${barLabel(experiment).toLowerCase()}`}
            </Text>
        )
    }
    const labelLeft = last ? last.left + last.width : 0
    /** The range always ends weeks after the last bar, so the label has room after the bar. */
    const labelInside = false
    const targetReached = experiment.status === LIST_STATUS.running && experiment.remainingDays === 0
    return (
        <Tooltip trackCursorAxis="x">
            <TooltipTrigger
                render={
                    <LinkPrimitive
                        to="#"
                        onClick={(event) => event.preventDefault()}
                        aria-label={`${experiment.name}, ${scheduleText(experiment)}`}
                        data-attr="timeline-bar"
                        className="group absolute inset-0 block focus-visible:outline-none"
                    />
                }
            >
                {solid && (
                    <span
                        className={cn(
                            'absolute top-1/2 h-5 -translate-y-1/2 rounded-sm transition-[filter] group-hover:brightness-110 group-focus-visible:ring-2 group-focus-visible:ring-ring',
                            solid.clippedStart ? 'rounded-l-none' : '',
                            halted || projected ? 'rounded-r-none' : ''
                        )}
                        style={{ left: `${solid.left}%`, width: `${solid.width}%`, background: fill }}
                    />
                )}
                {halted && (
                    <span
                        className="absolute top-1/2 h-5 -translate-y-1/2 rounded-r-sm border border-l-0"
                        style={{
                            borderColor: experiment.status === LIST_STATUS.paused ? TONE.paused : TONE.running,
                            left: `${halted.left}%`,
                            width: `${halted.width}%`,
                            ...HATCH,
                        }}
                    />
                )}
                {projected && (
                    <span
                        className="absolute top-1/2 h-5 -translate-y-1/2 rounded-r-sm border border-dashed border-l-0"
                        style={{
                            left: `${projected.left}%`,
                            width: `${projected.width}%`,
                            borderColor: TONE.running,
                            background: tint('data-color-1', 10),
                        }}
                    />
                )}
                {last && (
                    <span
                        className={cn(
                            'absolute top-1/2 flex -translate-y-1/2 items-center gap-1 whitespace-nowrap text-xs text-muted-foreground [&_svg]:size-3.5',
                            labelInside ? '-translate-x-full pr-1.5' : 'pl-1.5'
                        )}
                        style={{ left: `${labelInside ? (projected ?? halted ?? solid)!.left : labelLeft}%` }}
                    >
                        {targetReached && <IconCheck className="text-success-foreground" />}
                        {experiment.status === LIST_STATUS.paused && <IconPause />}
                        {barLabel(experiment)}
                    </span>
                )}
            </TooltipTrigger>
            <TooltipContent side="top" align="start">
                <BarTooltip experiment={experiment} />
            </TooltipContent>
        </Tooltip>
    )
}

/** How many experiments ran on each day, to show overlap and busy weeks at a glance. */
function ConcurrencyRow({ experiments, range }: { experiments: ListExperiment[]; range: Range }): JSX.Element {
    const counts = Array.from({ length: range.days }, (_, day) => {
        const date = range.start.add(day, 'day')
        if (date.isAfter(today)) {
            return null
        }
        return experiments.filter((experiment) => {
            if (!experiment.startDate || date.isBefore(experiment.startDate)) {
                return false
            }
            const stop = experiment.endDate ?? experiment.haltedAt
            return !stop || !date.isAfter(stop)
        }).length
    })
    const peak = Math.max(1, ...counts.map((count) => count ?? 0))
    return (
        <div className="flex h-8 items-end gap-px" aria-label="Experiments running each day">
            {counts.map((count, day) => (
                <div
                    key={day}
                    title={count === null ? undefined : `${formatDay(range.start.add(day, 'day'))}: ${count} running`}
                    className="flex-1 rounded-t-[1px]"
                    style={{ height: count ? `${(count / peak) * 100}%` : 0, background: TONE.neutral }}
                />
            ))}
        </div>
    )
}

function groupExperiments(
    experiments: ListExperiment[],
    group: TimelineGroup
): { key: string; label: string; items: ListExperiment[] }[] {
    const byStart = [...experiments].sort((a, b) => (a.startDate ?? '9999').localeCompare(b.startDate ?? '9999'))
    if (group === TIMELINE_GROUP.none) {
        return [{ key: 'all', label: '', items: byStart }]
    }
    if (group === TIMELINE_GROUP.status) {
        return STATUS_ORDER.map((status) => ({
            key: status,
            label: STATUS_LABEL[status],
            items: byStart.filter((experiment) => experiment.status === status),
        })).filter((entry) => entry.items.length > 0)
    }
    const owners = [...new Set(byStart.map((experiment) => experiment.createdBy))].sort()
    return owners.map((owner) => ({
        key: owner,
        label: owner,
        items: byStart.filter((experiment) => experiment.createdBy === owner),
    }))
}

export function TimelineControls({
    zoom,
    onZoomChange,
    group,
    onGroupChange,
}: {
    zoom: TimelineZoom
    onZoomChange: (zoom: TimelineZoom) => void
    group: TimelineGroup
    onGroupChange: (group: TimelineGroup) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <Select value={group} onValueChange={(value) => onGroupChange(value as TimelineGroup)}>
                <SelectTrigger size="sm" className="w-40" aria-label="Group by" data-attr="timeline-group-by">
                    <SelectValue>
                        {(value: TimelineGroup) =>
                            ({ none: 'No grouping', status: 'Group by status', owner: 'Group by creator' })[value]
                        }
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value="status">Group by status</SelectItem>
                    <SelectItem value="owner">Group by creator</SelectItem>
                    <SelectItem value="none">No grouping</SelectItem>
                </SelectContent>
            </Select>
            <ToggleGroup
                variant="outline"
                size="sm"
                value={[zoom]}
                onValueChange={(value: string[]) => value[0] && onZoomChange(value[0] as TimelineZoom)}
                aria-label="Time range"
                data-attr="timeline-zoom"
            >
                {Object.values(TIMELINE_ZOOM).map((key) => (
                    <ToggleGroupItem key={key} value={key}>
                        {ZOOM_RANGE[key].label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}

/** The whole history: from a week before the first launch to the last estimated end, so any part can be scrolled to. */
function fullRange(experiments: ListExperiment[], zoom: TimelineZoom): Range {
    const windowStart = today.subtract(ZOOM_RANGE[zoom].before, 'day')
    const windowEnd = today.add(ZOOM_RANGE[zoom].after, 'day')
    const starts = experiments.flatMap((experiment) => (experiment.startDate ? [dayjs(experiment.startDate)] : []))
    const ends = experiments.flatMap((experiment) =>
        experiment.status === LIST_STATUS.running && experiment.remainingDays
            ? [today.add(experiment.remainingDays + 3, 'day')]
            : []
    )
    const first = starts.reduce((earliest, date) => (date.isBefore(earliest) ? date : earliest), windowStart)
    const last = ends.reduce((latest, date) => (date.isAfter(latest) ? date : latest), windowEnd).add(21, 'day')
    const start = first.subtract(7, 'day').startOf('month')
    return { start, days: last.diff(start, 'day') }
}

/** Width of an element, kept current as the scene resizes. */
function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
    const ref = useRef<T>(null)
    const [width, setWidth] = useState(0)
    useEffect(() => {
        if (!ref.current) {
            return
        }
        const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
        observer.observe(ref.current)
        return () => observer.disconnect()
    }, [])
    return [ref, width]
}

const NAME_COLUMN = 'sticky left-0 z-10 w-44 shrink-0 border-r border-border bg-card @4xl/main-content:w-64'

export function PrototypeExperimentsTimeline({
    experiments,
    zoom,
    group,
    scrollToDate,
}: {
    experiments: ListExperiment[]
    zoom: TimelineZoom
    group: TimelineGroup
    /** Opens the timeline with this day at the left edge instead of the default window around today. */
    scrollToDate?: string
}): JSX.Element {
    const range = fullRange(experiments, zoom)
    const [scrollerRef, scrollerWidth] = useWidth<HTMLDivElement>()
    const [nameRef, nameWidth] = useWidth<HTMLDivElement>()
    const windowDays = ZOOM_RANGE[zoom].before + ZOOM_RANGE[zoom].after
    const pxPerDay = scrollerWidth > nameWidth ? (scrollerWidth - nameWidth) / windowDays : 0
    const trackWidth = Math.round(range.days * pxPerDay)
    const { months, lines } = useTicks(range, zoom)
    const todayLeft = toPercent(today, range)
    const groups = groupExperiments(experiments, group)

    const scrollToDay = (date: dayjs.Dayjs, behavior: ScrollBehavior): void => {
        scrollerRef.current?.scrollTo({ left: Math.max(daysFrom(date, range.start), 0) * pxPerDay, behavior })
    }
    /** The range control sets the window, so a change of range or width puts the window back around today. */
    useLayoutEffect(() => {
        if (pxPerDay > 0) {
            scrollToDay(scrollToDate ? dayjs(scrollToDate) : today.subtract(ZOOM_RANGE[zoom].before, 'day'), 'auto')
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [zoom, pxPerDay, scrollToDate])
    const step = (direction: 1 | -1): void => {
        scrollerRef.current?.scrollBy({ left: direction * (windowDays / 2) * pxPerDay, behavior: 'smooth' })
    }

    const track = { width: trackWidth }
    return (
        <Card size="sm" flush className="overflow-clip py-0" data-attr="experiments-timeline">
            <div ref={scrollerRef} className="overflow-x-auto" data-attr="timeline-scroller">
                <div className="flex w-max min-w-full flex-col">
                    <div className="flex border-b border-border">
                        <div
                            ref={nameRef}
                            className={cn(NAME_COLUMN, 'flex items-end justify-between gap-1 px-3 pb-1')}
                        >
                            <Text size="xs" variant="muted">
                                Experiment
                            </Text>
                            <span className="flex items-center gap-0.5">
                                <Button
                                    size="icon-xs"
                                    aria-label="Earlier"
                                    tooltip="Earlier"
                                    onClick={() => step(-1)}
                                    data-attr="timeline-earlier"
                                >
                                    <IconChevronLeft />
                                </Button>
                                <Button
                                    size="xs"
                                    onClick={() =>
                                        scrollToDay(today.subtract(ZOOM_RANGE[zoom].before, 'day'), 'smooth')
                                    }
                                    data-attr="timeline-today"
                                >
                                    Today
                                </Button>
                                <Button
                                    size="icon-xs"
                                    aria-label="Later"
                                    tooltip="Later"
                                    onClick={() => step(1)}
                                    data-attr="timeline-later"
                                >
                                    <IconChevronRight />
                                </Button>
                            </span>
                        </div>
                        <div className="relative h-9 shrink-0" style={track}>
                            {months.map((month) => (
                                <Text
                                    key={`${month.label}-${month.left}`}
                                    size="xs"
                                    weight="medium"
                                    className="absolute top-1.5 border-l border-border pl-1.5"
                                    style={{ left: `${month.left}%` }}
                                >
                                    {month.label}
                                </Text>
                            ))}
                            <span
                                className="absolute bottom-0.5 -translate-x-1/2 rounded-sm bg-primary px-1 text-[10px] font-medium leading-4 text-primary-foreground"
                                style={{ left: `${todayLeft}%` }}
                            >
                                Today
                            </span>
                        </div>
                    </div>
                    <div className="flex border-b border-border">
                        <div className={cn(NAME_COLUMN, 'flex items-center px-3')}>
                            <Text size="xs" variant="muted">
                                Running each day
                            </Text>
                        </div>
                        <div className="relative shrink-0 pt-1" style={track}>
                            <Gridlines lines={lines} todayLeft={todayLeft} />
                            <ConcurrencyRow experiments={experiments} range={range} />
                        </div>
                    </div>
                    {groups.map((entry) => (
                        <div key={entry.key} role="rowgroup">
                            {entry.label && (
                                <div className="flex border-b border-border bg-fill-hover">
                                    <div className="sticky left-0 flex items-center gap-2 px-3 py-1">
                                        <Text size="xs" weight="medium">
                                            {entry.label}
                                        </Text>
                                        <Text size="xs" variant="muted">
                                            {entry.items.length}
                                        </Text>
                                    </div>
                                </div>
                            )}
                            {entry.items.map((experiment) => (
                                <div
                                    key={experiment.key}
                                    role="row"
                                    className="group/row flex border-b border-border last:border-b-0"
                                >
                                    <div
                                        className={cn(
                                            NAME_COLUMN,
                                            'flex min-w-0 flex-col justify-center px-3 py-1.5 group-hover/row:bg-muted'
                                        )}
                                    >
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
                                    <div
                                        className="relative min-h-11 shrink-0 group-hover/row:bg-fill-hover"
                                        style={track}
                                    >
                                        <Gridlines lines={lines} todayLeft={todayLeft} />
                                        <ExperimentBar experiment={experiment} range={range} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    ))}
                </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-3 py-2">
                <Legend label="Running" swatchStyle={{ background: TONE.running }} />
                <Legend
                    label="Estimated running time"
                    swatchStyle={{ border: `1px dashed ${TONE.running}`, background: tint('data-color-1', 10) }}
                />
                <Legend
                    label="Paused or exposure frozen"
                    swatchStyle={{ ...HATCH, border: `1px solid ${TONE.paused}` }}
                />
                <Legend label="Won" swatchStyle={{ background: TONE.won }} />
                <Legend label="Lost" swatchStyle={{ background: TONE.lost }} />
                <Legend label="Inconclusive" swatchStyle={{ background: TONE.neutral }} />
                <Legend label="Stopped early" swatchStyle={{ background: TONE.stoppedEarly }} />
                <Text size="xs" variant="muted" className="ml-auto">
                    Scroll sideways or use the arrows to see earlier experiments
                </Text>
            </div>
        </Card>
    )
}

function Legend({ swatchStyle, label }: { swatchStyle: React.CSSProperties; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-[2px]" style={swatchStyle} />
            <Text size="xs" variant="muted">
                {label}
            </Text>
        </span>
    )
}
