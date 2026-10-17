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
    const { messageCategoryNames, timezone } = useValues(sendCalendarLogic)
    const isBroadcast = send.kind === 'broadcast'
    const moveReason = send.state === 'planned' ? moveBlockedReason(send) : null
    const categoryType = send.category.type ? CATEGORY_TYPES[send.category.type] : null
    const categoryName = send.category.id ? messageCategoryNames[send.category.id] : null

    return (
        <div className="flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-3 p-3" data-attr="send-calendar-send-details">
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1">
                    <LemonTag type={isBroadcast ? 'primary' : 'muted'}>
                        {isBroadcast ? 'Broadcast' : 'Workflow'}
                    </LemonTag>
                    <LemonTag type={STATE_TAGS[send.state].type}>{STATE_TAGS[send.state].label}</LemonTag>
                </div>
                <div className="text-base font-semibold">{send.name}</div>
            </div>
            <dl className="m-0 grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-2 text-sm">
                <dt className="text-secondary">When</dt>
                <dd className="m-0">{send.at.tz(timezone).format('ddd, MMM D [at] h:mm A')}</dd>
                {send.repeat ? (
                    <>
                        <dt className="text-secondary">Repeats</dt>
                        <dd className="m-0">{send.repeat}</dd>
                    </>
                ) : null}
                <dt className="text-secondary">Sends to</dt>
                <dd className="m-0 min-w-0">
                    <SendCalendarAudience audience={send.audience} />
                </dd>
                <dt className="text-secondary">Category</dt>
                <dd className="m-0 min-w-0">
                    {categoryType || categoryName ? (
                        <div className="flex min-w-0 items-center gap-1">
                            {categoryType ? (
                                <LemonTag size="small" type={categoryType.type}>
                                    {categoryType.label}
                                </LemonTag>
                            ) : null}
                            {categoryName ? <span className="truncate">{categoryName}</span> : null}
                        </div>
                    ) : (
                        <span className="text-secondary">No category</span>
                    )}
                </dd>
                {send.createdBy ? (
                    <>
                        <dt className="text-secondary">Created by</dt>
                        <dd className="m-0 flex items-center gap-1">
                            <ProfilePicture
                                user={{ first_name: send.createdBy.first_name, email: send.createdBy.email }}
                                size="xs"
                            />
                            {send.createdBy.first_name || send.createdBy.email}
                        </dd>
                    </>
                ) : null}
            </dl>
            {send.category.type === 'transactional' && !send.audience.address ? (
                <div className="text-xs text-warning">
                    Transactional emails go to everyone in the audience, including people who unsubscribed.
                </div>
            ) : null}
            {send.state === 'paused' ? (
                <div className="text-xs text-secondary">
                    This schedule paused because its recipients changed. Open it to schedule it again.
                </div>
            ) : moveReason ? (
                <div className="text-xs text-secondary">{moveReason}</div>
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
