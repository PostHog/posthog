import clsx from 'clsx'
import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'

import { SendCalendarDraggableSend } from './SendCalendarDraggableSend'
import { SendCalendarDropZone } from './SendCalendarDropZone'
import { sendCalendarLogic } from './sendCalendarLogic'

export function SendCalendarWeek(): JSX.Element {
    const { days, sendsByDay, today } = useValues(sendCalendarLogic)

    return (
        <div
            className="grid grid-cols-7 overflow-hidden rounded border bg-surface-primary"
            data-attr="send-calendar-week"
        >
            {days.map((day, index) => {
                const sends = sendsByDay[day] ?? []
                return (
                    <div key={day} className={clsx('flex min-w-0 flex-col', index < 6 && 'border-r')}>
                        <div className="border-b bg-surface-secondary px-2 py-1 text-xs font-semibold">
                            <span
                                className={clsx(
                                    day === today && 'rounded-full bg-accent px-1.5 py-0.5 text-primary-inverse'
                                )}
                            >
                                {dayjs.utc(day).format('ddd D')}
                            </span>
                        </div>
                        <SendCalendarDropZone day={day} className="flex min-h-80 flex-1 flex-col gap-0.5 p-1">
                            {sends.length ? (
                                sends.map((send) => <SendCalendarDraggableSend key={send.key} send={send} />)
                            ) : (
                                <span className="px-1 py-2 text-xs text-muted">No sends</span>
                            )}
                        </SendCalendarDropZone>
                    </div>
                )
            })}
        </div>
    )
}
