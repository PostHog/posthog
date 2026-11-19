// PROTOTYPE (throwaway): overview C, timeline. The next 14 days as a strip and what happened recently lead;
// numbers follow in one line.
import clsx from 'clsx'

import { Button, Card, CardGroup, Dot, Heading } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { KindDot } from './KindDot'
import { openInCalendar } from './openInCalendar'
import { ACTIVITY, TODAY, entriesBetween, formatCount, percent } from './prototypeData'
import { UpcomingList } from './UpcomingList'

const TONE_DOT = { default: 'default', success: 'success', warning: 'warning', destructive: 'destructive' } as const

function ago(at: dayjs.Dayjs): string {
    const minutes = dayjs().diff(at, 'minute')
    if (minutes < 60) {
        return `${minutes} min ago`
    }
    if (at.isSame(TODAY, 'day')) {
        return `Today ${at.format('H:mm')}`
    }
    return at.format('ddd, MMM D H:mm')
}

export function OverviewTimeline(): JSX.Element {
    const days = Array.from({ length: 14 }, (_, i) => TODAY.add(i, 'day'))
    const entries = entriesBetween(TODAY, TODAY.add(14, 'day'))
    return (
        <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                    <Heading size="sm">Next 14 days</Heading>
                    <Button variant="link" onClick={() => openInCalendar()}>
                        Open calendar
                    </Button>
                </div>
                <div className="grid grid-cols-7 gap-1 @min-[56rem]:grid-cols-14">
                    {days.map((d) => {
                        const dayEntries = entries.filter((e) => e.at.isSame(d, 'day'))
                        const oneOff = dayEntries.filter((e) => !e.repeatId)
                        const people = dayEntries.reduce((total, e) => total + e.people, 0)
                        return (
                            <button
                                key={d.format('YYYY-MM-DD')}
                                type="button"
                                onClick={() => openInCalendar()}
                                className={clsx(
                                    'flex min-h-20 flex-col gap-1 rounded-md border p-1.5 text-left hover:bg-fill-hover',
                                    d.isSame(TODAY, 'day') && 'border-primary'
                                )}
                            >
                                <span className="text-xxs text-muted-foreground">{d.format('ddd')}</span>
                                <span className="text-sm font-semibold">{d.date()}</span>
                                <span className="flex flex-wrap gap-0.5">
                                    {oneOff.map((e) => (
                                        <KindDot key={e.id} kind={e.kind} />
                                    ))}
                                    {dayEntries.length > oneOff.length ? (
                                        <span className="text-xxs text-subtle-foreground">
                                            +{dayEntries.length - oneOff.length}
                                        </span>
                                    ) : null}
                                </span>
                                <span className="mt-auto text-xxs tabular-nums text-muted-foreground">
                                    {formatCount(people)}
                                </span>
                            </button>
                        )
                    })}
                </div>
                <span className="text-xs text-muted-foreground">
                    Dots are broadcasts and one-time workflow runs. +N counts runs of repeating workflows. The number is
                    people reached that day.
                </span>
            </section>
            <div className="grid gap-6 @min-[56rem]:grid-cols-2">
                <section className="flex min-w-0 flex-col gap-2">
                    <Heading size="sm">Recent activity</Heading>
                    <CardGroup size="sm">
                        {ACTIVITY.map((item) => (
                            <Card key={item.id} size="sm">
                                <button
                                    type="button"
                                    className="flex w-full items-start gap-2 px-2 py-1.5 text-left text-sm"
                                    onClick={() => item.entryId && openInCalendar(item.entryId)}
                                >
                                    <Dot variant={TONE_DOT[item.tone]} className="mt-1.5" />
                                    <span className="flex min-w-0 flex-1 flex-col">
                                        <span>{item.text}</span>
                                        {item.detail ? (
                                            <span className="text-xs text-muted-foreground">{item.detail}</span>
                                        ) : null}
                                    </span>
                                    <span className="shrink-0 text-xs text-subtle-foreground">{ago(item.at)}</span>
                                </button>
                            </Card>
                        ))}
                    </CardGroup>
                </section>
                <section className="flex min-w-0 flex-col gap-2">
                    <Heading size="sm">Coming up</Heading>
                    <UpcomingList days={14} limit={6} />
                </section>
            </div>
            <section className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t pt-3 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Last 30 days, email</span>
                <span>{percent(0.986)} delivered</span>
                <span>{percent(0.52)} opened</span>
                <span>{percent(0.19)} clicked</span>
                <span className="text-warning-foreground">Bounce rate 4.1% this week</span>
            </section>
        </div>
    )
}
