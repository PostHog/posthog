import { useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Badge, Dot, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { releaseLogic } from './releaseLogic'
import { ReleaseEvent, ReleaseSpan, STAGE_TONE } from './releaseUtils'

const DAY = 30
const BEFORE = 17
const AFTER = 60
const NAME = 280
const ROW = 48
const HEADER = 56
const OVERSCAN = 6

const SPAN_LOOK: Record<ReleaseSpan['kind'], { top: number; height: number; badge?: 'info' | 'warning' | 'default' }> =
    {
        flag: { top: 23, height: 2 },
        early_access: { top: 38, height: 4, badge: 'warning' },
        experiment: { top: 12, height: 24, badge: 'info' },
        experiment_done: { top: 12, height: 24, badge: 'default' },
    }

function markersByDay(
    events: ReleaseEvent[],
    start: dayjs.Dayjs,
    total: number
): { day: string; events: ReleaseEvent[] }[] {
    const end = start.add(total, 'day')
    const days = new Map<string, ReleaseEvent[]>()
    for (const event of events) {
        if (!event.upcoming) {
            continue
        }
        const date = dayjs(event.date)
        if (date.isBefore(start) || !date.isBefore(end)) {
            continue
        }
        const day = date.format('YYYY-MM-DD')
        const dayEvents = days.get(day)
        if (dayEvents) {
            dayEvents.push(event)
        } else {
            days.set(day, [event])
        }
    }
    return [...days].map(([day, dayEvents]) => ({ day, events: dayEvents }))
}

interface PlacedSpan extends ReleaseSpan {
    left: number
    width: number
}

const GROUP_LABEL: Partial<Record<ReleaseSpan['kind'], (count: number) => string>> = {
    experiment: (count) => `${count} experiments`,
    experiment_done: (count) => `${count} experiments complete`,
}

function mergeOverlapping(spans: ReleaseSpan[]): ReleaseSpan[] {
    const sorted = [...spans].sort((a, b) => a.kind.localeCompare(b.kind) || a.from.localeCompare(b.from))
    const groups: ReleaseSpan[][] = []
    for (const span of sorted) {
        const group = groups[groups.length - 1]
        const groupEnd = group?.reduce((latest, item) => (item.to > latest ? item.to : latest), '')
        if (group && group[0].kind === span.kind && span.from <= groupEnd) {
            group.push(span)
        } else {
            groups.push([span])
        }
    }
    const order = new Map(spans.map((span, index) => [span.key, index]))
    groups.sort((a, b) => (order.get(a[0].key) ?? 0) - (order.get(b[0].key) ?? 0))
    return groups.map((group) => {
        if (group.length === 1) {
            return group[0]
        }
        const first = group[0]
        return {
            key: `${first.key}-group`,
            kind: first.kind,
            from: first.from,
            to: group.reduce((latest, item) => (item.to > latest ? item.to : latest), first.to),
            label: GROUP_LABEL[first.kind]?.(group.length) ?? first.label,
            href: first.href,
        }
    })
}

function placeSpans(spans: ReleaseSpan[], start: dayjs.Dayjs, total: number): PlacedSpan[] {
    const end = start.add(total, 'day')
    const x = (date: string): number => Math.max(0, Math.min(total, dayjs(date).diff(start, 'day'))) * DAY
    const visible = spans.filter((span) => !dayjs(span.to).isBefore(start) && !dayjs(span.from).isAfter(end))
    const placed: PlacedSpan[] = []
    for (const span of mergeOverlapping(visible)) {
        const left = x(span.from)
        const width = Math.max(x(span.to) + DAY / 2 - left, span.kind === 'flag' ? 0 : DAY)
        if (width > 0) {
            placed.push({ ...span, left, width })
        }
    }
    return placed
}

export function ReleaseTimeline(): JSX.Element {
    const { filteredRows, dataLoading, search, stageFilter, decisionOnly } = useValues(releaseLogic)
    const today = dayjs().startOf('day')
    const start = today.subtract(BEFORE, 'day')
    const windowStart = start.format('YYYY-MM-DD')
    const placed = useMemo(
        () =>
            new Map(
                filteredRows.map((row) => [
                    row.id,
                    {
                        spans: placeSpans(row.spans, dayjs(windowStart), BEFORE + AFTER),
                        markers: markersByDay(row.events, dayjs(windowStart), BEFORE + AFTER),
                    },
                ])
            ),
        [filteredRows, windowStart]
    )
    const total = BEFORE + AFTER
    const days = Array.from({ length: total }, (_, index) => start.add(index, 'day'))
    const x = (date: string): number => Math.max(0, Math.min(total, dayjs(date).diff(start, 'day'))) * DAY
    const months = days.filter((day, index) => index === 0 || day.date() === 1)
    const scrollRef = useRef<HTMLDivElement>(null)
    const [scrollTop, setScrollTop] = useState(0)
    const [viewHeight, setViewHeight] = useState(0)

    useEffect(() => {
        const element = scrollRef.current
        if (!element) {
            return
        }
        setViewHeight(element.clientHeight)
        const observer = new ResizeObserver(() => setViewHeight(element.clientHeight))
        observer.observe(element)
        return () => observer.disconnect()
    }, [])

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = 0
        }
        setScrollTop(0)
    }, [search, stageFilter, decisionOnly])

    const first = Math.min(filteredRows.length, Math.max(0, Math.floor((scrollTop - HEADER) / ROW) - OVERSCAN))
    const last = Math.min(filteredRows.length, Math.ceil((scrollTop + viewHeight) / ROW) + OVERSCAN)

    return (
        <div
            ref={scrollRef}
            className="overflow-auto rounded-lg border border-border bg-background"
            style={{ maxHeight: 'calc(100vh - 230px)' }}
            onScroll={(event) => {
                setScrollTop(event.currentTarget.scrollTop)
                setViewHeight(event.currentTarget.clientHeight)
            }}
            data-attr="release-timeline"
        >
            <div className="relative" style={{ width: NAME + total * DAY }}>
                <div className="pointer-events-none absolute inset-y-0" style={{ left: NAME, width: total * DAY }}>
                    {days.map((day, index) =>
                        day.day() === 0 || day.day() === 6 ? (
                            <div
                                key={index}
                                className="absolute inset-y-0 bg-fill-hover"
                                style={{ left: index * DAY, width: DAY }}
                            />
                        ) : null
                    )}
                    <div className="absolute inset-y-0 w-px bg-primary" style={{ left: BEFORE * DAY + DAY / 2 }} />
                </div>
                <div className="sticky top-0 z-20 flex h-14 border-b border-border bg-background">
                    <div
                        className="sticky left-0 z-30 flex shrink-0 items-end border-r border-border bg-background px-3 pb-2 text-xs font-semibold text-muted-foreground"
                        style={{ width: NAME }}
                    >
                        Release
                    </div>
                    <div className="relative" style={{ width: total * DAY }}>
                        {months.map((month) => (
                            <div
                                key={month.format('YYYY-MM-DD')}
                                className="absolute top-1.5 pl-2 text-xs font-semibold"
                                style={{ left: month.diff(start, 'day') * DAY }}
                            >
                                {month.format('MMMM YYYY')}
                            </div>
                        ))}
                        {days.map((day, index) => (
                            <div
                                key={index}
                                className="absolute bottom-1.5 flex justify-center text-xs text-muted-foreground"
                                style={{ left: index * DAY, width: DAY }}
                            >
                                {day.isSame(today, 'day') ? (
                                    <span className="rounded-full bg-primary px-1.5 font-semibold text-primary-foreground">
                                        {day.date()}
                                    </span>
                                ) : (
                                    <span className={day.day() === 1 ? 'font-semibold text-foreground' : ''}>
                                        {day.date()}
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
                {first > 0 && <div style={{ height: first * ROW }} />}
                {filteredRows.slice(first, last).map((row) => (
                    <div
                        key={row.id}
                        className="group flex border-b border-border last:border-b-0"
                        style={{ height: ROW }}
                        data-attr="release-timeline-row"
                    >
                        <div className="sticky left-0 z-10 flex shrink-0" style={{ width: NAME }}>
                            <LinkPrimitive
                                to={urls.release(row.id)}
                                data-attr="release-timeline-release"
                                className="flex w-full items-center gap-2 border-r border-border bg-background px-3 text-foreground group-hover:bg-fill-hover"
                            >
                                <Dot variant={STAGE_TONE[row.stage]} />
                                <span className="flex min-w-0 flex-1 flex-col">
                                    <Text size="xs" weight="semibold" className="truncate">
                                        {row.name}
                                    </Text>
                                    <Text size="xs" variant="muted" className="truncate">
                                        {row.status}
                                    </Text>
                                </span>
                            </LinkPrimitive>
                        </div>
                        <div className="relative" style={{ width: total * DAY }}>
                            {(placed.get(row.id)?.spans ?? []).map((span) => {
                                const look = SPAN_LOOK[span.kind]
                                return (
                                    <div
                                        key={span.key}
                                        className="absolute flex"
                                        style={{
                                            left: span.left,
                                            width: span.width,
                                            top: look.top,
                                            height: look.height,
                                        }}
                                    >
                                        <LinkPrimitive
                                            to={span.href}
                                            title={span.label}
                                            className={cn(
                                                'flex h-full w-full',
                                                !look.badge && 'rounded-full bg-border'
                                            )}
                                        >
                                            {look.badge && (
                                                <Badge
                                                    variant={look.badge}
                                                    className={cn(
                                                        'h-full w-full justify-start overflow-hidden',
                                                        !span.label && 'p-0'
                                                    )}
                                                >
                                                    {span.label ? <span className="truncate">{span.label}</span> : null}
                                                </Badge>
                                            )}
                                        </LinkPrimitive>
                                    </div>
                                )
                            })}
                            {(placed.get(row.id)?.markers ?? []).map(({ day, events }) => (
                                <div
                                    key={day}
                                    title={events
                                        .map(
                                            (event) =>
                                                `${dayjs(event.date).format('D MMM')}: ${event.title} (${event.detail})`
                                        )
                                        .join('\n')}
                                    className="absolute flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-foreground"
                                    style={{ left: x(events[0].date) + DAY / 2 - 5, top: 16 }}
                                    data-attr="release-timeline-marker"
                                >
                                    <span className="size-2.5 rotate-45 border-2 border-primary bg-background" />
                                    {events.length === 1 ? events[0].title : `${events.length} changes`}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
                {last < filteredRows.length && <div style={{ height: (filteredRows.length - last) * ROW }} />}
                {!filteredRows.length && (
                    <div className="sticky left-0 p-8 text-xs text-muted-foreground">
                        {dataLoading ? 'Loading releases…' : 'No release matches these filters.'}
                    </div>
                )}
            </div>
        </div>
    )
}
