import clsx from 'clsx'
import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Popover } from 'lib/lemon-ui/Popover'

import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarSendButton } from './SendCalendarSendButton'
import { CalendarSend } from './sendCalendarUtils'

const MAX_VISIBLE_SENDS = 3

export function SendCalendarMonth(): JSX.Element {
    const { days, sendsByDay, today, anchorDate } = useValues(sendCalendarLogic)
    const month = anchorDate.slice(0, 7)

    return (
        <div className="overflow-hidden rounded border bg-surface-primary" data-attr="send-calendar-month">
            <div className="grid grid-cols-7 border-b bg-surface-secondary">
                {days.slice(0, 7).map((day) => (
                    <div key={day} className="px-2 py-1 text-xs font-semibold uppercase text-secondary">
                        {dayjs.utc(day).format('ddd')}
                    </div>
                ))}
            </div>
            <div className="grid grid-cols-7">
                {days.map((day, index) => {
                    const sends = sendsByDay[day] ?? []
                    const date = dayjs.utc(day)
                    return (
                        <div
                            key={day}
                            className={clsx(
                                'flex min-h-28 min-w-0 flex-col gap-0.5 p-1',
                                index % 7 !== 6 && 'border-r',
                                index < days.length - 7 && 'border-b',
                                !day.startsWith(month) && 'bg-surface-secondary'
                            )}
                        >
                            <div className="px-1 text-xs font-semibold">
                                <span
                                    className={clsx(
                                        day === today && 'rounded-full bg-accent px-1.5 py-0.5 text-primary-inverse',
                                        day !== today && !day.startsWith(month) && 'text-muted'
                                    )}
                                >
                                    {date.date() === 1 ? date.format('MMM D') : date.format('D')}
                                </span>
                            </div>
                            {sends.slice(0, MAX_VISIBLE_SENDS).map((send) => (
                                <SendCalendarSendButton key={send.key} send={send} />
                            ))}
                            {sends.length > MAX_VISIBLE_SENDS ? <MoreSends day={day} sends={sends} /> : null}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function MoreSends({ day, sends }: { day: string; sends: CalendarSend[] }): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-start"
            overlay={
                <div className="flex w-64 flex-col gap-0.5 p-1">
                    <div className="px-1 pb-1 text-xs font-semibold">{dayjs.utc(day).format('ddd, MMM D')}</div>
                    {sends.map((send) => (
                        <SendCalendarSendButton key={send.key} send={send} />
                    ))}
                </div>
            }
        >
            <LemonButton size="xsmall" sideIcon={null} onClick={() => setOpen(!open)} data-attr="send-calendar-more">
                +{sends.length - MAX_VISIBLE_SENDS} more
            </LemonButton>
        </Popover>
    )
}
