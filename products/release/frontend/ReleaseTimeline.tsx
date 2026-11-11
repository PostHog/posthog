import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { Badge, Dot, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { releaseLogic } from './releaseLogic'
import { ReleaseSpan, STAGE_TONE } from './releaseUtils'

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

export function ReleaseTimeline(): JSX.Element {
    const { filteredRows, dataLoading } = useValues(releaseLogic)
    const today = dayjs().startOf('day')
    const start = today.subtract(BEFORE, 'day')
    const total = BEFORE + AFTER
    const days = Array.from({ length: total }, (_, index) => start.add(index, 'day'))
    const x = (date: string): number => Math.max(0, Math.min(total, dayjs(date).diff(start, 'day'))) * DAY
    const months = days.filter((day, index) => index === 0 || day.date() === 1)
    const scrollRef = useRef<HTMLDivElement>(null)
    const [scrollTop, setScrollTop] = useState(0)
    const [viewHeight, setViewHeight] = useState(0)

    useEffect(() => {
        setViewHeight(scrollRef.current?.clientHeight ?? 0)
    }, [filteredRows.length])

    const first = Math.max(0, Math.floor((scrollTop - HEADER) / ROW) - OVERSCAN)
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
                            {row.spans.map((span) => {
                                if (
                                    dayjs(span.to).isBefore(start) ||
                                    dayjs(span.from).isAfter(start.add(total, 'day'))
                                ) {
                                    return null
                                }
                                const left = x(span.from)
                                const width = Math.max(x(span.to) + DAY / 2 - left, span.kind === 'flag' ? 0 : DAY)
                                const look = SPAN_LOOK[span.kind]
                                return width > 0 ? (
                                    <div
                                        key={span.key}
                                        className="absolute flex"
                                        style={{ left, width, top: look.top, height: look.height }}
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
                                ) : null
                            })}
                            {row.events
                                .filter((event) => event.upcoming)
                                .map((event) => (
                                    <div
                                        key={event.key}
                                        title={`${dayjs(event.date).format('D MMM')}: ${event.title} (${event.detail})`}
                                        className="absolute flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-foreground"
                                        style={{ left: x(event.date) + DAY / 2 - 5, top: 16 }}
                                        data-attr="release-timeline-marker"
                                    >
                                        <span className="size-2.5 rotate-45 border-2 border-primary bg-background" />
                                        {event.title}
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
