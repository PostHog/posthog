import clsx from 'clsx'

import { IconBolt, IconCursorClick, IconEye, IconLetter } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { urls } from 'scenes/urls'

import type { EmailLogEventKindEnumApi } from 'products/messaging/frontend/generated/api.schemas'

import { ActivityEvent, ActivityRow, describeActivityEvent, isCustomEvent, relativeToSend } from './emailActivity'
import { EMAIL_STATUS_LABEL, EMAIL_STATUS_TAG, emailReasonText } from './emailLogStatus'

const EMAIL_EVENT_LABEL: Record<EmailLogEventKindEnumApi, string> = {
    queued: 'Email queued',
    sent: 'Email sent',
    delivered: 'Email delivered',
    opened: 'Opened the email',
    clicked: 'Clicked a link in the email',
    bounced: 'Email bounced',
    complained: 'Marked the email as spam',
    failed: "Email wasn't sent",
}

const FAILED_KINDS: EmailLogEventKindEnumApi[] = ['bounced', 'complained', 'failed']

function EventIcon({ event }: { event: ActivityEvent }): JSX.Element {
    if (event.event === '$pageview' || event.event === '$screen') {
        return <IconEye />
    }
    if (event.event === '$autocapture' || event.event === '$rageclick') {
        return <IconCursorClick />
    }
    return <IconBolt />
}

function TimeCell({ at, sentAt }: { at: string; sentAt: string }): JSX.Element {
    return (
        <Tooltip title={<TZLabel time={at} formatDate="MMM D, YYYY" formatTime="HH:mm:ss" noStyles />}>
            <span className="text-xs text-secondary whitespace-nowrap tabular-nums">{relativeToSend(at, sentAt)}</span>
        </Tooltip>
    )
}

export function TransactionalEmailActivityRow({ row, sentAt }: { row: ActivityRow; sentAt: string }): JSX.Element {
    if (row.kind === 'session') {
        return (
            <li className="flex items-center gap-3 pt-3 first:pt-0">
                <span className="text-xs font-semibold uppercase tracking-wide text-secondary">Session</span>
                <TZLabel time={row.at} className="text-xs text-secondary" />
                <span className="h-px flex-1 bg-border" />
                <ViewRecordingButton
                    sessionId={row.sessionId}
                    timestamp={row.at}
                    checkRecordingExists
                    openPlayerIn={RecordingPlayerType.Modal}
                    size="xsmall"
                    type="secondary"
                    label="Watch"
                    data-attr="transactional-email-activity-recording"
                />
            </li>
        )
    }
    if (row.kind === 'emailGroup') {
        return (
            <li className="flex flex-col gap-1 rounded border border-l-2 border-l-accent bg-surface-secondary px-3 py-2">
                {row.rows.map((emailRow) => {
                    const failed = FAILED_KINDS.includes(emailRow.event.kind)
                    const reason = emailReasonText(emailRow.event.reason)
                    return (
                        <div key={emailRow.key} className="flex items-center gap-3 min-w-0">
                            <span className={clsx('flex shrink-0 text-base', failed ? 'text-danger' : 'text-accent')}>
                                <IconLetter />
                            </span>
                            <span
                                className={clsx(
                                    'flex-1 min-w-0 text-sm font-semibold truncate',
                                    failed && 'text-danger'
                                )}
                            >
                                {EMAIL_EVENT_LABEL[emailRow.event.kind]}
                                {reason && <span className="font-normal text-secondary"> · {reason}</span>}
                            </span>
                            <TimeCell at={emailRow.at} sentAt={sentAt} />
                        </div>
                    )
                })}
            </li>
        )
    }
    if (row.kind === 'otherEmail') {
        return (
            <li className="flex items-center gap-3 px-2 -mx-2 py-1">
                <span className="flex shrink-0 text-base text-secondary">
                    <IconLetter />
                </span>
                <span className="flex-1 min-w-0 flex items-center gap-2 text-sm">
                    <span className="truncate">
                        Got{' '}
                        <Link
                            to={urls.transactionalEmailLogEntry(row.entry.message_id)}
                            data-attr="transactional-email-activity-other-email"
                        >
                            {row.entry.template_name || 'a deleted email'}
                        </Link>
                    </span>
                    <LemonTag size="small" type={EMAIL_STATUS_TAG[row.entry.status]} className="shrink-0">
                        {EMAIL_STATUS_LABEL[row.entry.status]}
                    </LemonTag>
                </span>
                <TimeCell at={row.at} sentAt={sentAt} />
            </li>
        )
    }
    const custom = isCustomEvent(row.event)
    const description = describeActivityEvent(row.event)
    return (
        <li className="flex items-center gap-3 px-2 -mx-2 py-1">
            <span className={clsx('flex shrink-0 text-base', custom ? 'text-warning' : 'text-secondary')}>
                <EventIcon event={row.event} />
            </span>
            <span className={clsx('flex-1 min-w-0 text-sm truncate', custom && 'font-semibold')} title={description}>
                {description}
                {row.count > 1 && <span className="font-normal text-secondary"> ×{row.count}</span>}
            </span>
            <TimeCell at={row.at} sentAt={sentAt} />
        </li>
    )
}
