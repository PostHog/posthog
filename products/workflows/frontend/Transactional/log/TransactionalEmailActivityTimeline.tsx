import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import {
    ACTIVITY_WINDOW_DAYS,
    PersonActivity,
    buildActivityTimeline,
    describeComeback,
    emailSentAt,
} from './emailActivity'
import { groupActivityRows } from './emailActivityGroups'
import { gapLabel } from './emailDeliverySteps'
import { TransactionalEmailActivityRail } from './TransactionalEmailActivityRail'
import { transactionalEmailLogEntryLogic } from './transactionalEmailLogEntryLogic'

/** How many events before the send show until the reader asks for more. */
const BEFORE_PREVIEW = 5

/** How many sessions or runs of events after the send show until the reader asks for more. */
const AFTER_GROUPS_PREVIEW = 5

function sendLabel(email: TransactionalEmailLogDetailApi, sentAt: string): string {
    const went = email.timeline.some((event) => event.kind === 'sent')
    if (email.status === 'bounced') {
        const bouncedAt = email.timeline.find((event) => event.kind === 'bounced')?.at
        const gap = bouncedAt ? gapLabel(bouncedAt, sentAt) : null
        return `Email sent, bounced${gap ? ` ${gap}` : ''}`
    }
    if (email.status === 'complained') {
        return 'Email sent, marked as spam'
    }
    if (email.status === 'failed') {
        return went ? 'Email sent, then failed' : "Email wasn't sent"
    }
    return 'Email sent'
}

function emptyAfterText(activity: PersonActivity, sentAt: string): string | null {
    if (activity.after.length) {
        return null
    }
    const days = pluralize(ACTIVITY_WINDOW_DAYS, 'day')
    if (!activity.before.length) {
        return `No events from this person in the ${days} before or after this email.`
    }
    return dayjs().isAfter(dayjs(sentAt).add(ACTIVITY_WINDOW_DAYS, 'day'))
        ? `No activity in your product in the ${days} after this email.`
        : 'No activity in your product since this email.'
}

/** The person's loaded activity on one rail, with the email pinned where it went out. */
export function TransactionalEmailActivityTimeline({
    email,
    activity,
}: {
    email: TransactionalEmailLogDetailApi
    activity: PersonActivity
}): JSX.Element {
    const { beforeExpanded, afterExpanded, otherEmails, otherEmailsFailed, otherEmailsLoading } = useValues(
        transactionalEmailLogEntryLogic
    )
    const { showAllBefore, showAllAfter, loadOtherEmails } = useActions(transactionalEmailLogEntryLogic)

    const before = beforeExpanded ? activity.before : activity.before.slice(-BEFORE_PREVIEW)
    const hiddenBefore = activity.before.length - before.length
    // Other emails before the send only show alongside the events the reader chose to show.
    const earliestShown = before[0]?.timestamp ?? email.created_at
    const shownOtherEmails = otherEmails.filter((entry) => !dayjs(entry.created_at).isBefore(earliestShown))
    const sentAt = emailSentAt(email)
    const timeline = buildActivityTimeline([...before, ...activity.after], shownOtherEmails, sentAt)
    const groupsBefore = groupActivityRows(timeline.before)
    const allGroupsAfter = groupActivityRows(timeline.after)
    const groupsAfter = afterExpanded ? allGroupsAfter : allGroupsAfter.slice(0, AFTER_GROUPS_PREVIEW)
    const hiddenAfter = allGroupsAfter
        .slice(groupsAfter.length)
        .reduce((total, group) => total + Math.max(group.eventCount, group.rows.length), 0)
    const nothingAround = !activity.before.length && !activity.after.length
    const noSessions = !nothingAround && ![...groupsBefore, ...allGroupsAfter].some((group) => group.sessionId)
    return (
        <div className="flex flex-col gap-3">
            {otherEmailsFailed && !otherEmailsLoading && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadOtherEmails(email),
                        'data-attr': 'transactional-email-other-emails-retry',
                    }}
                >
                    This person's other emails couldn't load. Check your connection and try again.
                </LemonBanner>
            )}
            <TransactionalEmailActivityRail
                before={groupsBefore}
                after={groupsAfter}
                sentAt={sentAt}
                failed={['bounced', 'complained', 'failed'].includes(email.status)}
                sendLabel={sendLabel(email, sentAt)}
                sendDetail={email.template_name || null}
                comeback={describeComeback(activity, email.timeline)}
                emptyAfter={emptyAfterText(activity, sentAt)}
                hiddenBefore={hiddenBefore}
                onShowEarlier={showAllBefore}
                hiddenAfter={hiddenAfter}
                onShowLater={showAllAfter}
            />
            {(noSessions || (activity.hasMoreAfter && hiddenAfter === 0)) && (
                <div className="flex flex-col gap-1 text-xs text-secondary">
                    {noSessions && <span>These events have no session, so there's no replay to watch.</span>}
                    {activity.hasMoreAfter && hiddenAfter === 0 && (
                        <span>
                            Showing the first {activity.after.length} events after the email. See the rest on the
                            person's page.
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}
