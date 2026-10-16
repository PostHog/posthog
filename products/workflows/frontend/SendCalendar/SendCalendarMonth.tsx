import clsx from 'clsx'
import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Popover } from 'lib/lemon-ui/Popover'

import { SendCalendarDraggableSend } from './SendCalendarDraggableSend'
import { SendCalendarDropZone } from './SendCalendarDropZone'
import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarNewSendButton } from './SendCalendarNewSendButton'
import { CalendarSend } from './sendCalendarUtils'

const MAX_VISIBLE_SENDS = 3

export function SendCalendarMonth(): JSX.Element {
    const { days, sendsByDay, today, anchorDate } = useValues(sendCalendarLogic)
    const month = anchorDate.slice(0, 7)

    return (
        // On a wide screen the weeks share the height under the toolbar, so the grid fills the screen.
        <div
            className="flex flex-col overflow-hidden rounded border bg-surface-primary @min-[60rem]:min-h-[calc(100vh-16rem)]"
            data-attr="send-calendar-month"
        >
            <div className="grid grid-cols-7 border-b bg-surface-secondary">
                {days.slice(0, 7).map((day) => (
                    <div key={day} className="px-2 py-1 text-xs font-semibold uppercase text-secondary">
                        {dayjs.utc(day).format('ddd')}
                    </div>
                ))}
            </div>
            <div className="grid flex-1 auto-rows-fr grid-cols-7">
                {days.map((day, index) => {
                    const sends = sendsByDay[day] ?? []
                    const date = dayjs.utc(day)
                    return (
                        <SendCalendarDropZone
                            key={day}
                            day={day}
                            className={clsx(
                                'group flex min-h-28 min-w-0 flex-col gap-0.5 p-1',
                                index % 7 !== 6 && 'border-r',
                                index < days.length - 7 && 'border-b',
                                !day.startsWith(month) && 'bg-surface-secondary'
                            )}
                        >
                            <div className="flex h-6 items-center justify-between pl-1 text-xs font-semibold">
                                <span
                                    className={clsx(
                                        day === today && 'rounded-full bg-accent px-1.5 py-0.5 text-primary-inverse',
                                        day !== today && !day.startsWith(month) && 'text-muted'
                                    )}
                                >
                                    {date.date() === 1 ? date.format('MMM D') : date.format('D')}
                                </span>
                                {day >= today ? <SendCalendarNewSendButton day={day} /> : null}
                            </div>
                            {sends.slice(0, MAX_VISIBLE_SENDS).map((send) => (
                                <SendCalendarDraggableSend key={send.key} send={send} />
                            ))}
                            {sends.length > MAX_VISIBLE_SENDS ? <MoreSends day={day} sends={sends} /> : null}
                        </SendCalendarDropZone>
                    )
                })}
            </div>
        </div>
    )
}

function MoreSends({ day, sends }: { day: string; sends: CalendarSend[] }): JSX.Element {
    const [open, setOpen] = useState(false)
    // The first sends already show in the day cell, and each send can render as a draggable only once.
    const hiddenSends = sends.slice(MAX_VISIBLE_SENDS)
    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-start"
            overlay={
                <div className="flex w-64 flex-col gap-0.5 p-1">
                    <div className="px-1 pb-1 text-xs font-semibold">{dayjs.utc(day).format('ddd, MMM D')}</div>
                    {hiddenSends.map((send) => (
                        <SendCalendarDraggableSend key={send.key} send={send} />
                    ))}
                </div>
            }
        >
            <LemonButton size="xsmall" sideIcon={null} onClick={() => setOpen(!open)} data-attr="send-calendar-more">
                +{hiddenSends.length} more
            </LemonButton>
        </Popover>
    )
}
