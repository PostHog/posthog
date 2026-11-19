// PROTOTYPE (throwaway): variant D. A month grid that stays readable: a repeating workflow shows once in the
// Repeating row instead of on every day, a day shows at most three entries, and transactional and
// event-triggered messages show as one volume bar per day.
import clsx from 'clsx'
import { useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { CalendarFilters, matches, showsVolume } from './calendarFilters'
import type { CalendarSelection } from './CalendarPrototype'
import { KindDot } from './KindDot'
import { CalendarEntry, TODAY, formatCount, volumeFor } from './prototypeData'
import { RepeatingRow } from './RepeatingRow'

const MAX_PER_DAY = 3
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function gridDays(month: dayjs.Dayjs): dayjs.Dayjs[] {
    const first = month.startOf('month')
    const start = first.subtract((first.day() + 6) % 7, 'day')
    const last = month.endOf('month')
    const days: dayjs.Dayjs[] = []
    for (let d = start; d.isBefore(last) || days.length % 7 !== 0; d = d.add(1, 'day')) {
        days.push(d)
    }
    return days
}

export function CalendarMonthView({
    month,
    entries,
    filters,
    selection,
    onSelect,
    onMove,
}: {
    month: dayjs.Dayjs
    entries: CalendarEntry[]
    filters: CalendarFilters
    selection: CalendarSelection
    onSelect: (selection: CalendarSelection) => void
    onMove: (id: string, day: dayjs.Dayjs) => void
}): JSX.Element {
    const [dragOver, setDragOver] = useState<string | null>(null)
    const days = gridDays(month)
    const visible = entries.filter((e) => matches(e, filters) && (filters.showRepeats || !e.repeatId))
    const volumes = days.map((d) => volumeFor(d))
    const maxVolume = Math.max(1, ...volumes.map((v) => (v ? v.transactional + v.triggered : 0)))
    const selectedId = selection && 'entryId' in selection ? selection.entryId : null

    return (
        <div className="flex flex-col gap-2">
            {!filters.showRepeats ? <RepeatingRow entries={entries} filters={filters} onSelect={onSelect} /> : null}
            <div className="grid grid-cols-7 overflow-hidden rounded-md border">
                {WEEKDAYS.map((name) => (
                    <div key={name} className="border-b bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
                        {name}
                    </div>
                ))}
                {days.map((d, index) => {
                    const key = d.format('YYYY-MM-DD')
                    const dayEntries = visible.filter((e) => e.at.isSame(d, 'day'))
                    const volume = volumes[index]
                    const total = volume ? volume.transactional + volume.triggered : 0
                    const inMonth = d.isSame(month, 'month')
                    const isToday = d.isSame(TODAY, 'day')
                    const canDrop = !d.isBefore(TODAY, 'day')
                    return (
                        <div
                            key={key}
                            className={clsx(
                                'flex min-h-28 min-w-0 flex-col gap-0.5 border-b border-r p-1',
                                !inMonth && 'bg-muted/50',
                                dragOver === key && 'bg-fill-selected'
                            )}
                            onDragOver={(event) => {
                                if (canDrop) {
                                    event.preventDefault()
                                    setDragOver(key)
                                }
                            }}
                            onDragLeave={() => setDragOver(null)}
                            onDrop={(event) => {
                                event.preventDefault()
                                setDragOver(null)
                                const id = event.dataTransfer.getData('text/plain')
                                const entry = entries.find((e) => e.id === id)
                                if (entry && !entry.at.isSame(d, 'day')) {
                                    onMove(id, d)
                                    lemonToast.success(`Moved ${entry.name} to ${d.format('ddd, MMM D')}.`)
                                }
                            }}
                        >
                            <div className="flex items-center justify-between">
                                <span
                                    className={clsx(
                                        'text-xs',
                                        isToday
                                            ? 'rounded-full bg-primary px-1.5 font-semibold text-primary-foreground'
                                            : inMonth
                                              ? 'text-foreground'
                                              : 'text-subtle-foreground'
                                    )}
                                >
                                    {d.date()}
                                </span>
                            </div>
                            {dayEntries.slice(0, MAX_PER_DAY).map((entry) => {
                                const draggable = entry.state === 'scheduled' && !entry.repeatId
                                return (
                                    <button
                                        key={entry.id}
                                        type="button"
                                        draggable={draggable}
                                        onDragStart={(event) => event.dataTransfer.setData('text/plain', entry.id)}
                                        onClick={() => onSelect({ entryId: entry.id })}
                                        className={clsx(
                                            'flex min-w-0 items-center gap-1 rounded-sm px-1 py-0.5 text-left text-xs hover:bg-fill-hover',
                                            selectedId === entry.id && 'bg-fill-selected',
                                            draggable && 'cursor-grab',
                                            entry.state === 'failed' && 'text-destructive-foreground',
                                            entry.state === 'paused' && 'text-warning-foreground',
                                            entry.state === 'sent' && 'text-muted-foreground'
                                        )}
                                    >
                                        <KindDot kind={entry.kind} />
                                        <span className="shrink-0 tabular-nums">{entry.at.format('H:mm')}</span>
                                        <span className="truncate">{entry.name}</span>
                                    </button>
                                )
                            })}
                            {dayEntries.length > MAX_PER_DAY ? (
                                <button
                                    type="button"
                                    className="rounded-sm px-1 text-left text-xs text-muted-foreground hover:bg-fill-hover"
                                    onClick={() => onSelect({ day: key })}
                                >
                                    {dayEntries.length - MAX_PER_DAY} more
                                </button>
                            ) : null}
                            {volume && showsVolume(filters) ? (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <button
                                                type="button"
                                                className="mt-auto flex items-center gap-1 rounded-sm px-1 text-xxs text-muted-foreground hover:bg-fill-hover"
                                                onClick={() => onSelect({ day: key })}
                                            />
                                        }
                                    >
                                        <span
                                            className="h-1.5 rounded-xs bg-muted-foreground/40"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ width: `${Math.max(8, (total / maxVolume) * 60)}%` }}
                                        />
                                        <span className="tabular-nums">{formatCount(total)}</span>
                                        {volume.failed > 10 ? (
                                            <Badge variant="destructive">{volume.failed} failed</Badge>
                                        ) : null}
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        <div className="flex flex-col">
                                            <span>Transactional: {formatCount(volume.transactional)}</span>
                                            <span>Event-triggered workflows: {formatCount(volume.triggered)}</span>
                                            <span>Failed: {volume.failed}</span>
                                        </div>
                                    </TooltipContent>
                                </Tooltip>
                            ) : null}
                        </div>
                    )
                })}
            </div>
            <span className="text-xs text-muted-foreground">
                Drag a scheduled broadcast or workflow to another day to move it.
            </span>
        </div>
    )
}
