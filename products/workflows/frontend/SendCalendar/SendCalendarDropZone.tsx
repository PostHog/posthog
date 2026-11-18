import { useDroppable } from '@dnd-kit/core'
import clsx from 'clsx'
import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'

import { sendCalendarLogic } from './sendCalendarLogic'
import { CalendarSend, dropTarget } from './sendCalendarUtils'

export function SendCalendarDropZone({
    day,
    className,
    children,
}: {
    day: string
    className?: string
    children: React.ReactNode
}): JSX.Element {
    const { timezone } = useValues(sendCalendarLogic)
    const { setNodeRef, isOver, active } = useDroppable({ id: day })
    const send = active?.data.current?.send as CalendarSend | undefined
    const accepts = !!send && !!dropTarget(send, day, timezone, dayjs())

    return (
        <div
            ref={setNodeRef}
            className={clsx(className, isOver && accepts && 'bg-primary-highlight')}
            data-attr="send-calendar-day"
        >
            {children}
        </div>
    )
}
