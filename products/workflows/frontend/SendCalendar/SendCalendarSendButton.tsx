import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'

import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarSendDetails } from './SendCalendarSendDetails'
import { SendCalendarSendLabel } from './SendCalendarSendLabel'
import { CalendarSend } from './sendCalendarUtils'

export function SendCalendarSendButton({ send }: { send: CalendarSend }): JSX.Element {
    const { timezone } = useValues(sendCalendarLogic)
    const { reportSendOpened } = useActions(sendCalendarLogic)
    const [open, setOpen] = useState(false)

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-start"
            overlay={<SendCalendarSendDetails send={send} />}
        >
            <LemonButton
                size="xsmall"
                fullWidth
                sideIcon={null}
                onClick={() => {
                    if (!open) {
                        reportSendOpened(send)
                    }
                    setOpen(!open)
                }}
                data-attr="send-calendar-send"
            >
                <SendCalendarSendLabel send={send} timezone={timezone} />
            </LemonButton>
        </Popover>
    )
}
