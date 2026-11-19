// PROTOTYPE (throwaway): variant E. One list by day: what goes out next, and for what already went out, how it
// did, without opening a metrics page. Starts today; the last 7 days are one click away.
import clsx from 'clsx'
import { useState } from 'react'

import { Badge, Button, Card, CardGroup } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { CalendarFilters, matches, showsVolume } from './calendarFilters'
import type { CalendarSelection } from './CalendarPrototype'
import { EntryBadges } from './EntryBadges'
import { CalendarEntry, TODAY, formatCount, percent, volumeFor } from './prototypeData'

function relative(at: dayjs.Dayjs): string {
    const days = at.startOf('day').diff(TODAY, 'day')
    if (days === 0) {
        return 'Today'
    }
    if (days === 1) {
        return 'Tomorrow'
    }
    if (days === -1) {
        return 'Yesterday'
    }
    return days > 0 ? `In ${days} days` : `${-days} days ago`
}

function Outcome({ entry }: { entry: CalendarEntry }): JSX.Element | null {
    const r = entry.results
    if (entry.state === 'failed') {
        return <span className="text-destructive-foreground">{entry.error}</span>
    }
    if (!r) {
        return <span className="text-muted-foreground">{formatCount(entry.people)} people</span>
    }
    return (
        <span className="tabular-nums text-muted-foreground">
            {formatCount(r.sent)} sent · {percent(r.delivered / r.sent)} delivered
            {entry.channel !== 'sms' ? ` · ${percent(r.opened / r.delivered)} opened` : ''} ·{' '}
            {percent(r.clicked / r.delivered)} clicked
        </span>
    )
}

export function CalendarAgendaView({
    entries,
    filters,
    selection,
    onSelect,
}: {
    entries: CalendarEntry[]
    filters: CalendarFilters
    selection: CalendarSelection
    onSelect: (selection: CalendarSelection) => void
}): JSX.Element {
    const [showPast, setShowPast] = useState(false)
    const [daysAhead, setDaysAhead] = useState(14)
    const start = showPast ? TODAY.subtract(7, 'day') : TODAY
    const days = Array.from({ length: TODAY.add(daysAhead, 'day').diff(start, 'day') }, (_, i) => start.add(i, 'day'))
    const selectedId = selection && 'entryId' in selection ? selection.entryId : null

    return (
        <div className="flex flex-col gap-4">
            <div>
                <Button variant="outline" onClick={() => setShowPast(!showPast)}>
                    {showPast ? 'Hide the last 7 days' : 'Show the last 7 days'}
                </Button>
            </div>
            {days.map((d) => {
                const dayEntries = entries.filter((e) => e.at.isSame(d, 'day') && matches(e, filters))
                const shown = dayEntries.filter((e) => filters.showRepeats || !e.repeatId)
                const repeats = dayEntries.filter((e) => !filters.showRepeats && e.repeatId)
                const volume = showsVolume(filters) ? volumeFor(d) : null
                if (!shown.length && !repeats.length && !volume) {
                    return null
                }
                const isToday = d.isSame(TODAY, 'day')
                return (
                    <section key={d.format('YYYY-MM-DD')} className="flex flex-col gap-1">
                        <div className="flex flex-wrap items-baseline gap-2">
                            <h4
                                className={clsx(
                                    'mb-0 text-sm font-semibold',
                                    d.isBefore(TODAY, 'day') && 'text-muted-foreground'
                                )}
                            >
                                {d.format('dddd, MMM D')}
                            </h4>
                            {isToday ? <Badge variant="info">Today</Badge> : null}
                            {volume ? (
                                <button
                                    type="button"
                                    className="ml-auto text-xs text-muted-foreground hover:underline"
                                    onClick={() => onSelect({ day: d.format('YYYY-MM-DD') })}
                                >
                                    {formatCount(volume.transactional)} transactional · {formatCount(volume.triggered)}{' '}
                                    event-triggered
                                    {volume.failed > 10 ? ` · ${volume.failed} failed` : ''}
                                </button>
                            ) : null}
                        </div>
                        <CardGroup size="sm">
                            {shown.map((entry) => (
                                <Card
                                    key={entry.id}
                                    size="sm"
                                    className={clsx(selectedId === entry.id && 'bg-fill-selected')}
                                >
                                    <button
                                        type="button"
                                        className="grid w-full grid-cols-[3rem_1fr] items-start gap-x-3 gap-y-0.5 px-2 py-1.5 text-left text-sm @min-[40rem]:grid-cols-[3rem_minmax(12rem,1fr)_auto_minmax(14rem,1.4fr)]"
                                        onClick={() => onSelect({ entryId: entry.id })}
                                    >
                                        <span className="tabular-nums text-muted-foreground">
                                            {entry.at.format('H:mm')}
                                        </span>
                                        <span className="min-w-0 truncate font-medium">{entry.name}</span>
                                        <span className="col-start-2 @min-[40rem]:col-start-auto">
                                            <EntryBadges
                                                kind={entry.kind}
                                                state={entry.state}
                                                channel={entry.channel}
                                                repeats={!!entry.repeatId}
                                            />
                                        </span>
                                        <span className="col-start-2 text-xs @min-[40rem]:col-start-auto @min-[40rem]:text-right">
                                            <Outcome entry={entry} />
                                            {entry.state === 'scheduled' ? (
                                                <span className="text-subtle-foreground"> · {relative(entry.at)}</span>
                                            ) : null}
                                        </span>
                                    </button>
                                </Card>
                            ))}
                        </CardGroup>
                        {repeats.length ? (
                            <div className="flex flex-wrap items-center gap-1 pl-2 text-xs text-muted-foreground">
                                <span>Repeating:</span>
                                {repeats.map((entry) => (
                                    <Button
                                        key={entry.id}
                                        variant="link-muted"
                                        size="inline"
                                        onClick={() => onSelect({ entryId: entry.id })}
                                    >
                                        {entry.at.format('H:mm')} {entry.name}
                                    </Button>
                                ))}
                            </div>
                        ) : null}
                    </section>
                )
            })}
            <div>
                <Button variant="outline" onClick={() => setDaysAhead(daysAhead + 14)}>
                    Show 14 more days
                </Button>
            </div>
        </div>
    )
}
