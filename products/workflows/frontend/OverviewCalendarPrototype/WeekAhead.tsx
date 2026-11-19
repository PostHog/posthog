// PROTOTYPE (throwaway): a mini calendar of the next 7 days. Picking a day filters the list under it; the
// Calendar link opens the full calendar.
import clsx from 'clsx'
import { useState } from 'react'

import { Button, Card, CardAction, CardContent, CardHeader, CardTitle } from '@posthog/quill'

import { EmptyInsight } from './EmptyInsight'
import { KindDot } from './KindDot'
import { openInCalendar } from './openInCalendar'
import { TODAY, entriesBetween } from './prototypeData'
import { prototypeToast } from './prototypeToast'
import { UpcomingList } from './UpcomingList'

export function WeekAhead({ noSends }: { noSends: boolean }): JSX.Element {
    const [picked, setPicked] = useState<number | null>(null)
    const days = Array.from({ length: 7 }, (_, i) => TODAY.add(i, 'day'))
    const entries = noSends
        ? []
        : entriesBetween(TODAY, TODAY.add(7, 'day')).filter((e) => e.state === 'scheduled' || e.state === 'paused')
    const pickedDay = picked === null ? undefined : days[picked]
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>
                    {pickedDay ? `Goes out ${pickedDay.format('ddd, MMM D')}` : 'Goes out in the next 7 days'}
                </CardTitle>
                <CardAction>
                    <Button variant="link" size="inline" onClick={() => openInCalendar()}>
                        Calendar
                    </Button>
                </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                <div className="grid grid-cols-7 gap-1">
                    {days.map((d, i) => {
                        const dayEntries = entries.filter((e) => e.at.isSame(d, 'day'))
                        const oneOff = dayEntries.filter((e) => !e.repeatId)
                        const repeats = dayEntries.length - oneOff.length
                        const isToday = d.isSame(TODAY, 'day')
                        const isPicked = picked === i
                        return (
                            <button
                                key={d.format('YYYY-MM-DD')}
                                type="button"
                                aria-pressed={isPicked}
                                onClick={() => setPicked(isPicked ? null : i)}
                                className={clsx(
                                    'flex flex-col items-center gap-1 rounded-md border px-0.5 py-1.5',
                                    isPicked ? 'border-primary bg-fill-selected' : 'hover:bg-fill-hover',
                                    isToday && !isPicked && 'border-foreground/40'
                                )}
                            >
                                <span className="text-xxs uppercase text-muted-foreground">{d.format('dd')}</span>
                                <span className={clsx('text-sm tabular-nums', isToday && 'font-semibold')}>
                                    {d.format('D')}
                                </span>
                                <span className="flex h-2 items-center gap-0.5">
                                    {oneOff.slice(0, 3).map((e) => (
                                        <KindDot key={e.id} kind={e.kind} />
                                    ))}
                                </span>
                                <span className="h-3 text-xxs text-muted-foreground">
                                    {repeats ? `+${repeats}` : ''}
                                </span>
                            </button>
                        )
                    })}
                </div>
                {noSends ? (
                    <EmptyInsight title="Nothing is scheduled" detail="Scheduled broadcasts and workflows show here.">
                        <Button variant="outline" size="sm" onClick={() => prototypeToast('a new broadcast')}>
                            New broadcast
                        </Button>
                    </EmptyInsight>
                ) : (
                    <UpcomingList days={7} limit={pickedDay ? 8 : 4} compact day={pickedDay} />
                )}
            </CardContent>
        </Card>
    )
}
