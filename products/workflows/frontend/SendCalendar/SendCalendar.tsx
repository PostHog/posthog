import {
    DndContext,
    DragEndEvent,
    DragOverlay,
    PointerSensor,
    pointerWithin,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { SendCalendarLegend } from './SendCalendarLegend'
import { SendCalendarList } from './SendCalendarList'
import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarMonth } from './SendCalendarMonth'
import { SendCalendarSendLabel } from './SendCalendarSendLabel'
import { CalendarSend, CalendarTypeFilter, CalendarView } from './sendCalendarUtils'
import { SendCalendarWeek } from './SendCalendarWeek'

export function SendCalendar(): JSX.Element {
    const { view, typeFilter, periodLabel, timezone, scheduledFlows, scheduledFlowsLoading, loadFailed } =
        useValues(sendCalendarLogic)
    const { setView, setTypeFilter, goToToday, goForward, goBackward, moveSend } = useActions(sendCalendarLogic)
    const [draggedSend, setDraggedSend] = useState<CalendarSend | null>(null)
    // A drag starts only after the pointer moves a few pixels, so a click on a send still opens its details.
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

    const onDragEnd = ({ active, over }: DragEndEvent): void => {
        setDraggedSend(null)
        const send = active.data.current?.send as CalendarSend | undefined
        if (send && over) {
            moveSend(send, String(over.id))
        }
    }

    return (
        <div className="@container flex flex-col gap-2" data-attr="send-calendar">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-1">
                    <LemonButton type="secondary" size="small" onClick={goToToday} data-attr="send-calendar-today">
                        Today
                    </LemonButton>
                    <LemonButton
                        size="small"
                        icon={<IconChevronLeft />}
                        onClick={goBackward}
                        tooltip={view === 'month' ? 'Previous month' : 'Previous week'}
                        data-attr="send-calendar-previous"
                    />
                    <LemonButton
                        size="small"
                        icon={<IconChevronRight />}
                        onClick={goForward}
                        tooltip={view === 'month' ? 'Next month' : 'Next week'}
                        data-attr="send-calendar-next"
                    />
                    <h3 className="mb-0 ml-1 text-base font-semibold">{periodLabel}</h3>
                    {scheduledFlowsLoading && scheduledFlows ? <Spinner className="ml-1" /> : null}
                </div>
                <div className="flex items-center gap-2">
                    <LemonSegmentedButton<CalendarView>
                        size="small"
                        value={view}
                        onChange={setView}
                        options={[
                            { value: 'month', label: 'Month' },
                            { value: 'week', label: 'Week' },
                        ]}
                        data-attr="send-calendar-view"
                    />
                    <LemonSelect<CalendarTypeFilter>
                        size="small"
                        value={typeFilter}
                        onChange={setTypeFilter}
                        dropdownMatchSelectWidth={false}
                        options={[
                            { value: 'all', label: 'All sends' },
                            { value: 'broadcasts', label: 'Broadcasts' },
                            { value: 'workflows', label: 'Workflows' },
                        ]}
                        data-attr="send-calendar-type"
                    />
                </div>
            </div>
            <div className="text-xs text-secondary">
                Times use the project time zone ({timezone}). Drafts, transactional emails, and event-triggered
                workflows do not show.{' '}
                <span className="hidden @min-[40rem]:inline">Drag a scheduled send to another day to move it.</span>
            </div>
            <SendCalendarLegend />
            {scheduledFlowsLoading && !scheduledFlows ? (
                <div className="flex justify-center p-8">
                    <Spinner className="text-2xl" />
                </div>
            ) : loadFailed ? (
                <div className="rounded border bg-surface-primary p-8 text-center text-secondary">
                    Couldn't load the scheduled sends. Refresh the page to try again.
                </div>
            ) : !scheduledFlows?.length ? (
                <div className="rounded border bg-surface-primary p-8 text-center text-secondary">
                    Nothing is scheduled in this period. Active broadcasts, and scheduled workflows with an email step,
                    show here.
                </div>
            ) : (
                <DndContext
                    sensors={sensors}
                    // The day under the pointer takes the drop, as in other calendars, even when the dragged
                    // label overlaps the next day.
                    collisionDetection={pointerWithin}
                    onDragStart={({ active }) => setDraggedSend((active.data.current?.send as CalendarSend) ?? null)}
                    onDragEnd={onDragEnd}
                    onDragCancel={() => setDraggedSend(null)}
                >
                    <div className="hidden @min-[40rem]:block">
                        {view === 'month' ? <SendCalendarMonth /> : <SendCalendarWeek />}
                    </div>
                    <div className="@min-[40rem]:hidden">
                        <SendCalendarList />
                    </div>
                    <DragOverlay dropAnimation={null}>
                        {draggedSend ? (
                            <div className="cursor-grabbing rounded border bg-surface-primary px-2 py-1 text-xs shadow">
                                <SendCalendarSendLabel send={draggedSend} timezone={timezone} />
                            </div>
                        ) : null}
                    </DragOverlay>
                </DndContext>
            )}
        </div>
    )
}
