// PROTOTYPE (throwaway): every entry of one day, and that day's transactional volume per template.
import { IconX } from '@posthog/icons'
import { Button, Card, CardContent, CardGroup, CardHeader, CardTitle, Separator } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { CalendarFilters, matches, showsVolume } from './calendarFilters'
import type { CalendarSelection } from './CalendarPrototype'
import { EntryBadges } from './EntryBadges'
import { CalendarEntry, formatCount, volumeFor } from './prototypeData'

export function DayPane({
    day,
    entries,
    filters,
    onSelect,
    onClose,
}: {
    day: dayjs.Dayjs
    entries: CalendarEntry[]
    filters: CalendarFilters
    onSelect: (selection: CalendarSelection) => void
    onClose: () => void
}): JSX.Element {
    const dayEntries = entries.filter((e) => e.at.isSame(day, 'day') && matches(e, filters))
    const volume = volumeFor(day)
    return (
        <Card className="w-full @min-[64rem]:w-80 shrink-0 self-start">
            <CardHeader>
                <div className="flex items-start justify-between gap-2">
                    <CardTitle>{day.format('dddd, MMMM D')}</CardTitle>
                    <Button size="icon-sm" aria-label="Close" tooltip="Close" onClick={onClose}>
                        <IconX />
                    </Button>
                </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
                <CardGroup size="sm">
                    {dayEntries.map((entry) => (
                        <Card key={entry.id} size="sm">
                            <button
                                type="button"
                                className="flex w-full flex-col gap-1 px-2 py-1 text-left text-sm"
                                onClick={() => onSelect({ entryId: entry.id })}
                            >
                                <span className="font-medium">
                                    {entry.at.format('H:mm')} {entry.name}
                                </span>
                                <EntryBadges
                                    kind={entry.kind}
                                    state={entry.state}
                                    channel={entry.channel}
                                    repeats={!!entry.repeatId}
                                />
                            </button>
                        </Card>
                    ))}
                </CardGroup>
                {volume && showsVolume(filters) ? (
                    <>
                        <Separator />
                        <span className="text-sm font-medium">
                            Transactional emails: {formatCount(volume.transactional)}
                        </span>
                        {volume.byTemplate.map((t) => (
                            <div key={t.name} className="flex justify-between text-sm text-muted-foreground">
                                <span>{t.name}</span>
                                <span className="tabular-nums">{formatCount(t.count)}</span>
                            </div>
                        ))}
                        <span className="text-sm font-medium">
                            Event-triggered workflows: {formatCount(volume.triggered)}
                        </span>
                        {volume.failed ? (
                            <span className="text-sm text-destructive-foreground">{volume.failed} failed</span>
                        ) : null}
                        <Button variant="outline">Open the log for this day</Button>
                    </>
                ) : null}
            </CardContent>
        </Card>
    )
}
