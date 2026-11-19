import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { PersonActivity } from './emailActivity'
import { EmailActivityTimeline } from './EmailActivityTimeline'
import { transactionalEmailLogEntryLogic } from './transactionalEmailLogEntryLogic'

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
            <EmailActivityTimeline
                email={email}
                activity={activity}
                beforeExpanded={beforeExpanded}
                afterExpanded={afterExpanded}
                onShowEarlier={showAllBefore}
                onShowLater={showAllAfter}
                otherEmails={otherEmails}
            />
        </div>
    )
}
