// PROTOTYPE (throwaway, never merged). Round 1 of PostHog/michaelr-context#420: the calendar of everything
// scheduled and sent, as a month grid (D) and as an agenda (E), next to today's calendar (F), switchable via
// `?variant=`. Built as one self-contained page, so any navigation shape can mount it.
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Button, InputGroup, InputGroupInput } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { SendCalendar } from '../SendCalendar/SendCalendar'
import { CalendarAgendaView } from './CalendarAgendaView'
import { CalendarEmptyState } from './CalendarEmptyState'
import { CalendarFilterMenu } from './CalendarFilterMenu'
import { CalendarFilters, DEFAULT_FILTERS } from './calendarFilters'
import { CalendarMonthView } from './CalendarMonthView'
import { DayPane } from './DayPane'
import { EntryPane } from './EntryPane'
import { KindDot } from './KindDot'
import { CalendarEntry, TIMEZONE_LABEL, TODAY, entriesBetween } from './prototypeData'
import { PrototypeSwitcher, PrototypeVariant, usePrototypeVariant } from './PrototypeSwitcher'

export const CALENDAR_VARIANTS: PrototypeVariant[] = [
    { key: 'D', name: 'Month, repeats folded', flags: 'low use: drag to reschedule, type filter' },
    { key: 'E', name: 'Agenda with results', flags: 'low use: Week/Month toggle' },
    { key: 'F', name: "Today's calendar", flags: 'low use: every calendar control' },
]

export type CalendarSelection = { entryId: string } | { day: string } | null

export function CalendarPrototype(): JSX.Element {
    const variant = usePrototypeVariant(CALENDAR_VARIANTS)
    const { searchParams } = useValues(router)
    const [filters, setFilters] = useState<CalendarFilters>(DEFAULT_FILTERS)
    const [monthAnchor, setMonthAnchor] = useState(TODAY.startOf('month'))
    const [selection, setSelection] = useState<CalendarSelection>(
        searchParams.entry ? { entryId: String(searchParams.entry) } : null
    )
    // Moves from dragging, kept in memory only.
    const [moved, setMoved] = useState<Record<string, dayjs.Dayjs>>({})
    const newAccount = searchParams.account === 'new'
    const toggleAccount = (): void => {
        const { location, hashParams } = router.values
        router.actions.replace(
            location.pathname,
            { ...searchParams, account: newAccount ? undefined : 'new' },
            hashParams
        )
    }

    const allEntries = useMemo(() => {
        const entries = entriesBetween(TODAY.subtract(70, 'day'), TODAY.add(70, 'day'))
        return entries.map((entry) => (moved[entry.id] ? { ...entry, at: moved[entry.id] } : entry))
    }, [moved])

    const selectedEntry: CalendarEntry | undefined =
        selection && 'entryId' in selection ? allEntries.find((e) => e.id === selection.entryId) : undefined
    const selectedDay = selection && 'day' in selection ? dayjs(selection.day) : undefined

    const moveEntry = (id: string, toDay: dayjs.Dayjs): void => {
        const entry = allEntries.find((e) => e.id === id)
        if (entry) {
            setMoved({ ...moved, [id]: toDay.hour(entry.at.hour()).minute(entry.at.minute()) })
        }
    }

    if (variant.key === 'F') {
        return (
            <>
                <SendCalendar />
                <PrototypeSwitcher variants={CALENDAR_VARIANTS} page="Calendar" />
            </>
        )
    }

    return (
        <div data-quill className="@container flex flex-col gap-3 pb-20">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-1">
                    {variant.key === 'D' ? (
                        <>
                            <Button variant="outline" onClick={() => setMonthAnchor(TODAY.startOf('month'))}>
                                Today
                            </Button>
                            <Button
                                size="icon"
                                aria-label="Previous month"
                                tooltip="Previous month"
                                onClick={() => setMonthAnchor(monthAnchor.subtract(1, 'month'))}
                            >
                                <IconChevronLeft />
                            </Button>
                            <Button
                                size="icon"
                                aria-label="Next month"
                                tooltip="Next month"
                                onClick={() => setMonthAnchor(monthAnchor.add(1, 'month'))}
                            >
                                <IconChevronRight />
                            </Button>
                            <h3 className="mb-0 ml-1 text-base font-semibold">{monthAnchor.format('MMMM YYYY')}</h3>
                        </>
                    ) : (
                        <h3 className="mb-0 text-base font-semibold">Coming up</h3>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <InputGroup size="sm" className="w-56">
                        <InputGroupInput
                            placeholder="Search by name"
                            value={filters.search}
                            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
                        />
                    </InputGroup>
                    <CalendarFilterMenu filters={filters} onChange={setFilters} />
                </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                    <KindDot kind="broadcast" /> Broadcast
                </span>
                <span className="inline-flex items-center gap-1">
                    <KindDot kind="workflow" /> Workflow
                </span>
                <span className="inline-flex items-center gap-1">
                    <span className="inline-block h-2 w-3 rounded-xs bg-muted-foreground/40" /> Transactional and
                    event-triggered messages per day
                </span>
                <span>Times in {TIMEZONE_LABEL}</span>
                <Button variant="link-muted" size="inline" className="ml-auto" onClick={toggleAccount}>
                    {newAccount ? 'Prototype: show a busy account' : 'Prototype: show a new account'}
                </Button>
            </div>
            <div className="flex flex-col gap-3 @min-[64rem]:flex-row">
                <div className="min-w-0 flex-1">
                    {newAccount ? (
                        <CalendarEmptyState />
                    ) : variant.key === 'D' ? (
                        <CalendarMonthView
                            month={monthAnchor}
                            entries={allEntries}
                            filters={filters}
                            selection={selection}
                            onSelect={setSelection}
                            onMove={moveEntry}
                        />
                    ) : (
                        <CalendarAgendaView
                            entries={allEntries}
                            filters={filters}
                            selection={selection}
                            onSelect={setSelection}
                        />
                    )}
                </div>
                {selectedEntry && !newAccount ? (
                    <EntryPane entry={selectedEntry} onClose={() => setSelection(null)} />
                ) : null}
                {selectedDay && !newAccount ? (
                    <DayPane
                        day={selectedDay}
                        entries={allEntries}
                        filters={filters}
                        onSelect={setSelection}
                        onClose={() => setSelection(null)}
                    />
                ) : null}
            </div>
            <PrototypeSwitcher variants={CALENDAR_VARIANTS} page="Calendar" />
        </div>
    )
}
