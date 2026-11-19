// PROTOTYPE (throwaway): each repeating workflow once, with its rule and next run, instead of on every day.
import { Card, CardGroup, Collapsible, CollapsibleContent, CollapsibleTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { CalendarFilters, matches } from './calendarFilters'
import type { CalendarSelection } from './CalendarPrototype'
import { KindDot } from './KindDot'
import { CHANNEL_LABEL, CalendarEntry, REPEATING, formatCount } from './prototypeData'

export function RepeatingRow({
    entries,
    filters,
    onSelect,
}: {
    entries: CalendarEntry[]
    filters: CalendarFilters
    onSelect: (selection: CalendarSelection) => void
}): JSX.Element | null {
    const now = dayjs()
    const rows = REPEATING.map((repeat) => ({
        repeat,
        next: entries.find((e) => e.repeatId === repeat.id && e.at.isAfter(now) && matches(e, filters)),
    })).filter((row) => row.next)
    if (!rows.length) {
        return null
    }
    const perWeek = rows.reduce(
        (total, { repeat }) =>
            total +
            Array.from({ length: 7 }, (_, i) => now.add(i, 'day')).filter(repeat.runsOn).length * repeat.peoplePerRun,
        0
    )
    return (
        <Collapsible defaultOpen className="rounded-md border">
            <CollapsibleTrigger className="w-full px-2 py-1.5 text-sm">
                Repeating workflows ({rows.length}) · about {formatCount(perWeek)} messages a week
            </CollapsibleTrigger>
            <CollapsibleContent>
                <CardGroup size="sm" className="p-2 pt-0">
                    {rows.map(({ repeat, next }) => (
                        <Card key={repeat.id} size="sm">
                            <button
                                type="button"
                                className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 px-2 py-1 text-left text-sm"
                                onClick={() => next && onSelect({ entryId: next.id })}
                            >
                                <KindDot kind="workflow" />
                                <span className="font-medium">{repeat.name}</span>
                                <span className="text-muted-foreground">{repeat.rule}</span>
                                <span className="text-muted-foreground">
                                    {CHANNEL_LABEL[repeat.channel]} · {repeat.audience} · about{' '}
                                    {formatCount(repeat.peoplePerRun)} people a run
                                </span>
                                <span className="ml-auto text-xs text-muted-foreground">
                                    Next: {next?.at.format('ddd, MMM D H:mm')}
                                </span>
                            </button>
                        </Card>
                    ))}
                </CardGroup>
            </CollapsibleContent>
        </Collapsible>
    )
}
