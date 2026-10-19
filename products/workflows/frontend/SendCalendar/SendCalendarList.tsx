import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'

import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarSendButton } from './SendCalendarSendButton'

export function SendCalendarList(): JSX.Element {
    const { days, sendsByDay } = useValues(sendCalendarLogic)
    const daysWithSends = days.filter((day) => sendsByDay[day]?.length)

    if (!daysWithSends.length) {
        return (
            <div className="rounded border bg-surface-primary p-4 text-center text-secondary">
                No sends in this period.
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2" data-attr="send-calendar-list">
            {daysWithSends.map((day) => (
                <div key={day} className="overflow-hidden rounded border bg-surface-primary">
                    <div className="border-b bg-surface-secondary px-2 py-1 text-xs font-semibold">
                        {dayjs.utc(day).format('ddd, MMM D')}
                    </div>
                    <div className="flex flex-col gap-0.5 p-1">
                        {sendsByDay[day].map((send) => (
                            <SendCalendarSendButton key={send.key} send={send} />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}
