import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconPause, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarSendDetails } from './SendCalendarSendDetails'
import { CalendarSend } from './sendCalendarUtils'

export function SendCalendarSendButton({ send }: { send: CalendarSend }): JSX.Element {
    const { timezone } = useValues(sendCalendarLogic)
    const { reportSendOpened } = useActions(sendCalendarLogic)
    const [open, setOpen] = useState(false)
    const isPast = send.state === 'sent' || send.state === 'failed'

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
                <span className={clsx('flex min-w-0 items-center gap-1', isPast && 'text-secondary')}>
                    <span
                        className={clsx(
                            'size-2 shrink-0 rounded-full',
                            send.kind === 'broadcast' ? 'bg-accent' : 'bg-[var(--color-product-workflows-light)]'
                        )}
                    />
                    <span className="shrink-0 font-semibold">{send.at.tz(timezone).format('h:mm A')}</span>
                    <span className="truncate font-normal">{send.name}</span>
                    {send.state === 'planned' && send.isRecurring ? (
                        <IconRefresh className="shrink-0 text-secondary" aria-label="Repeats" />
                    ) : null}
                    {send.state === 'paused' ? <IconPause className="shrink-0" aria-label="Paused" /> : null}
                    {send.state === 'sending' ? <Spinner className="shrink-0" /> : null}
                    {send.state === 'sent' ? <IconCheck className="shrink-0 text-success" aria-label="Sent" /> : null}
                    {send.state === 'failed' ? (
                        <IconWarning className="shrink-0 text-danger" aria-label="Failed" />
                    ) : null}
                </span>
            </LemonButton>
        </Popover>
    )
}
