import { useValues } from 'kea'

import { LemonButton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { sendCalendarLogic } from './sendCalendarLogic'
import { CalendarSend, CalendarSendState, moveBlockedReason } from './sendCalendarUtils'

const STATE_TAGS: Record<CalendarSendState, { label: string; type: LemonTagType }> = {
    planned: { label: 'Scheduled', type: 'warning' },
    paused: { label: 'Paused', type: 'muted' },
    sending: { label: 'Sending', type: 'completion' },
    sent: { label: 'Sent', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
}

export function SendCalendarSendDetails({ send }: { send: CalendarSend }): JSX.Element {
    const { timezone } = useValues(sendCalendarLogic)
    const isBroadcast = send.kind === 'broadcast'
    const moveReason = send.state === 'planned' ? moveBlockedReason(send) : null

    return (
        <div className="flex w-72 flex-col gap-2 p-2" data-attr="send-calendar-send-details">
            <div className="flex items-center gap-1">
                <LemonTag type={isBroadcast ? 'primary' : 'muted'}>{isBroadcast ? 'Broadcast' : 'Workflow'}</LemonTag>
                <LemonTag type={STATE_TAGS[send.state].type}>{STATE_TAGS[send.state].label}</LemonTag>
            </div>
            <div className="text-sm font-semibold">{send.name}</div>
            <div className="text-xs">
                <div>{send.at.tz(timezone).format('ddd, MMM D, YYYY [at] h:mm A')}</div>
                {send.repeat ? <div className="text-secondary">{send.repeat}</div> : null}
            </div>
            {send.state === 'paused' ? (
                <div className="text-xs text-secondary">
                    This schedule paused because its recipients changed. Open it to schedule it again.
                </div>
            ) : moveReason ? (
                <div className="text-xs text-secondary">{moveReason}</div>
            ) : null}
            {send.createdBy ? (
                <div className="flex items-center gap-1 text-xs text-secondary">
                    <ProfilePicture
                        user={{ first_name: send.createdBy.first_name, email: send.createdBy.email }}
                        size="xs"
                    />
                    Created by {send.createdBy.first_name || send.createdBy.email}
                </div>
            ) : null}
            <LemonButton
                type="primary"
                size="small"
                to={isBroadcast ? urls.broadcast(send.flowId) : urls.workflow(send.flowId, 'workflow')}
                data-attr="send-calendar-open"
            >
                {isBroadcast ? 'Open broadcast' : 'Open workflow'}
            </LemonButton>
        </div>
    )
}
