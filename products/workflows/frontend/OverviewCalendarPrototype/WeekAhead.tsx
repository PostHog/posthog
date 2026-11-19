// PROTOTYPE (throwaway): a mini calendar of the next 7 days, then what goes out, for overview B2.
import clsx from 'clsx'

import { Button, Card, CardAction, CardContent, CardHeader, CardTitle } from '@posthog/quill'

import { KindDot } from './KindDot'
import { openInCalendar } from './openInCalendar'
import { TODAY, entriesBetween } from './prototypeData'
import { UpcomingList } from './UpcomingList'

export function WeekAhead(): JSX.Element {
    const days = Array.from({ length: 7 }, (_, i) => TODAY.add(i, 'day'))
    const entries = entriesBetween(TODAY, TODAY.add(7, 'day')).filter(
        (e) => e.state === 'scheduled' || e.state === 'paused'
    )
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>Goes out in the next 7 days</CardTitle>
                <CardAction>
                    <Button variant="link" size="inline" onClick={() => openInCalendar()}>
                        Calendar
                    </Button>
                </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                <div className="grid grid-cols-7 gap-1">
                    {days.map((d) => {
                        const dayEntries = entries.filter((e) => e.at.isSame(d, 'day'))
                        const oneOff = dayEntries.filter((e) => !e.repeatId)
                        const repeats = dayEntries.length - oneOff.length
                        const isToday = d.isSame(TODAY, 'day')
                        return (
                            <button
                                key={d.format('YYYY-MM-DD')}
                                type="button"
                                onClick={() => openInCalendar()}
                                className={clsx(
                                    'flex flex-col items-center gap-1 rounded-md border px-0.5 py-1.5 hover:bg-fill-hover',
                                    isToday && 'border-primary'
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
                <UpcomingList days={7} limit={4} compact />
            </CardContent>
        </Card>
    )
}
