import { useValues } from 'kea'

import { LemonButton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { SendCalendarAudience } from './SendCalendarAudience'
import { sendCalendarLogic } from './sendCalendarLogic'
import { CalendarSend, CalendarSendState, SendCategory, moveBlockedReason } from './sendCalendarUtils'

const STATE_TAGS: Record<CalendarSendState, { label: string; type: LemonTagType }> = {
    planned: { label: 'Scheduled', type: 'warning' },
    paused: { label: 'Paused', type: 'muted' },
    sending: { label: 'Sending', type: 'completion' },
    sent: { label: 'Sent', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
}

const CATEGORY_TYPES: Record<NonNullable<SendCategory['type']>, { label: string; type: LemonTagType }> = {
    marketing: { label: 'Marketing', type: 'highlight' },
    transactional: { label: 'Transactional', type: 'default' },
}

export function SendCalendarSendDetails({ send }: { send: CalendarSend }): JSX.Element {
    const { messageCategoryNames } = useValues(sendCalendarLogic)
    const isBroadcast = send.kind === 'broadcast'
    const moveReason = send.state === 'planned' ? moveBlockedReason(send) : null
    const categoryType = send.category.type ? CATEGORY_TYPES[send.category.type] : null
    const categoryName = send.category.id ? messageCategoryNames[send.category.id] : null

    return (
        <div className="flex w-72 flex-col gap-2 p-2" data-attr="send-calendar-send-details">
            <div className="flex items-center gap-1">
                <LemonTag type={isBroadcast ? 'primary' : 'muted'}>{isBroadcast ? 'Broadcast' : 'Workflow'}</LemonTag>
                <LemonTag type={STATE_TAGS[send.state].type}>{STATE_TAGS[send.state].label}</LemonTag>
            </div>
            <div>
                <div className="text-sm font-semibold">{send.name}</div>
                {send.repeat ? <div className="text-xs text-secondary">{send.repeat}</div> : null}
            </div>
            <div className="flex flex-col gap-1">
                <div className="text-xs font-semibold text-secondary">Sends to</div>
                <SendCalendarAudience audience={send.audience} />
            </div>
            <div className="flex flex-col gap-1">
                <div className="text-xs font-semibold text-secondary">Message category</div>
                {categoryType || categoryName ? (
                    <div className="flex min-w-0 items-center gap-1 text-xs">
                        {categoryType ? (
                            <LemonTag size="small" type={categoryType.type}>
                                {categoryType.label}
                            </LemonTag>
                        ) : null}
                        {categoryName ? <span className="truncate">{categoryName}</span> : null}
                    </div>
                ) : (
                    <div className="text-xs text-secondary">No category</div>
                )}
                {send.category.type === 'transactional' && !send.audience.address ? (
                    <div className="text-xs text-warning">
                        Transactional emails go to everyone in the audience, including people who unsubscribed.
                    </div>
                ) : null}
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
