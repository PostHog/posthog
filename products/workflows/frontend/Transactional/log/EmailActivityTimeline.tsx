import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import type {
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogEntryApi,
} from 'products/messaging/frontend/generated/api.schemas'

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

/** The parts of a send the rail reads. Workflow emails pass their send time as `created_at` and the step name as `template_name`. */
export type ActivityEmail = Pick<TransactionalEmailLogDetailApi, 'status' | 'timeline' | 'created_at' | 'template_name'>

/** How many events before the send show until the reader asks for more. */
const BEFORE_PREVIEW = 5

/** How many sessions or runs of events after the send show until the reader asks for more. */
const AFTER_GROUPS_PREVIEW = 5

function sendLabel(email: ActivityEmail, sentAt: string): string {
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

export interface EmailActivityTimelineProps {
    email: ActivityEmail
    activity: PersonActivity
    beforeExpanded: boolean
    afterExpanded: boolean
    onShowEarlier: () => void
    onShowLater: () => void
    otherEmails?: TransactionalEmailLogEntryApi[]
}

/** The person's loaded activity on one rail, with the email pinned where it went out. */
export function EmailActivityTimeline({
    email,
    activity,
    beforeExpanded,
    afterExpanded,
    onShowEarlier,
    onShowLater,
    otherEmails = [],
}: EmailActivityTimelineProps): JSX.Element {
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
                onShowEarlier={onShowEarlier}
                hiddenAfter={hiddenAfter}
                onShowLater={onShowLater}
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
