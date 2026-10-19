import clsx from 'clsx'

import { IconCheck, IconPause, IconRefresh, IconSend, IconWarning } from '@posthog/icons'

import { CalendarSend } from './sendCalendarUtils'

export function SendCalendarSendLabel({ send, timezone }: { send: CalendarSend; timezone: string }): JSX.Element {
    const isPast = send.state === 'sent' || send.state === 'failed'
    return (
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
            {send.state === 'sending' ? <IconSend className="shrink-0" aria-label="Sending" /> : null}
            {send.state === 'sent' ? <IconCheck className="shrink-0 text-success" aria-label="Sent" /> : null}
            {send.state === 'failed' ? <IconWarning className="shrink-0 text-danger" aria-label="Failed" /> : null}
        </span>
    )
}
