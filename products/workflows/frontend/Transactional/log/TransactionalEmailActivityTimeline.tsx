import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { ACTIVITY_WINDOW_DAYS, PersonActivity, buildActivityTimeline, emailSentAt } from './emailActivity'
import { TransactionalEmailActivityRow } from './TransactionalEmailActivityRow'
import { TransactionalEmailActivitySummary } from './TransactionalEmailActivitySummary'
import { transactionalEmailLogEntryLogic } from './transactionalEmailLogEntryLogic'

/** How many events before the send show until the reader asks for more. */
const BEFORE_PREVIEW = 5

/** The person's loaded activity, split into what they did before and after the email. */
export function TransactionalEmailActivityTimeline({
    email,
    activity,
}: {
    email: TransactionalEmailLogDetailApi
    activity: PersonActivity
}): JSX.Element {
    const { beforeExpanded, otherEmails, otherEmailsFailed, otherEmailsLoading } = useValues(
        transactionalEmailLogEntryLogic
    )
    const { showAllBefore, loadOtherEmails } = useActions(transactionalEmailLogEntryLogic)

    const before = beforeExpanded ? activity.before : activity.before.slice(-BEFORE_PREVIEW)
    const hiddenBefore = activity.before.length - before.length
    const emailEvents = email.timeline.filter((event) => event.kind !== 'queued')
    // Other emails before the send only show alongside the events the reader chose to show.
    const earliestShown = before[0]?.timestamp ?? email.created_at
    const shownOtherEmails = otherEmails.filter((entry) => !dayjs(entry.created_at).isBefore(earliestShown))
    // Times read relative to when the email went out, which is what a reader compares against.
    const sentAt = emailSentAt(email)
    const timeline = buildActivityTimeline([...before, ...activity.after], emailEvents, shownOtherEmails, sentAt)
    const nothingAround = !activity.before.length && !activity.after.length
    return (
        <div className="flex flex-col gap-4">
            <TransactionalEmailActivitySummary after={activity.after} timeline={email.timeline} />
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
            {timeline.before.length > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                        <h4 className="text-sm font-semibold m-0">Before the email</h4>
                        {hiddenBefore > 0 && (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={showAllBefore}
                                data-attr="transactional-email-activity-show-earlier"
                            >
                                Show {pluralize(hiddenBefore, 'earlier event')}
                            </LemonButton>
                        )}
                    </div>
                    <ol className="flex flex-col gap-1 m-0 p-0 list-none">
                        {timeline.before.map((row) => (
                            <TransactionalEmailActivityRow key={row.key} row={row} sentAt={sentAt} />
                        ))}
                    </ol>
                </div>
            )}
            <div className="flex flex-col gap-2">
                <h4 className="text-sm font-semibold m-0">After the email</h4>
                <ol className="flex flex-col gap-1 m-0 p-0 list-none" data-attr="transactional-email-activity">
                    {timeline.after.map((row) => (
                        <TransactionalEmailActivityRow key={row.key} row={row} sentAt={sentAt} />
                    ))}
                </ol>
                {!activity.after.length && (
                    <p
                        className="text-sm text-secondary m-0 rounded border border-dashed px-3 py-2"
                        data-attr="transactional-email-activity-nothing-after"
                    >
                        {nothingAround
                            ? `No events from this person in the ${pluralize(ACTIVITY_WINDOW_DAYS, 'day')} before or after this email.`
                            : dayjs().isAfter(dayjs(sentAt).add(ACTIVITY_WINDOW_DAYS, 'day'))
                              ? `No activity in your product in the ${pluralize(ACTIVITY_WINDOW_DAYS, 'day')} after this email.`
                              : 'No activity in your product since this email.'}
                    </p>
                )}
                {activity.hasMoreAfter && (
                    <p className="text-xs text-secondary m-0">
                        Showing the first {activity.after.length} events after the email. See the rest on the person's
                        page.
                    </p>
                )}
            </div>
        </div>
    )
}
