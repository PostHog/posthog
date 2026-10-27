import { useDraggable } from '@dnd-kit/core'
import clsx from 'clsx'
import { useValues } from 'kea'

import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarSendButton } from './SendCalendarSendButton'
import { CalendarSend, moveBlockedReason } from './sendCalendarUtils'

export function SendCalendarDraggableSend({ send }: { send: CalendarSend }): JSX.Element {
    const { savingScheduleIds } = useValues(sendCalendarLogic)
    const canMove = !moveBlockedReason(send) && !(send.schedule && savingScheduleIds[send.schedule.id])
    // dnd-kit keeps one node for each draggable id. If a send renders as a draggable twice, the drag can
    // measure the wrong node, and the drop then finds no day.
    const { setNodeRef, listeners, isDragging } = useDraggable({
        id: send.key,
        data: { send },
        disabled: !canMove,
    })

    return (
        // The drag listeners sit on a wrapper, so a short click still reaches the button and opens the details.
        <div
            ref={setNodeRef}
            {...listeners}
            className={clsx('min-w-0', canMove && 'cursor-grab', isDragging && 'opacity-40')}
        >
            <SendCalendarSendButton send={send} />
        </div>
    )
}
