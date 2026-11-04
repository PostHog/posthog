import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { TransactionalEmailActivityTimeline } from './TransactionalEmailActivityTimeline'
import { transactionalEmailLogEntryLogic } from './transactionalEmailLogEntryLogic'

export function TransactionalEmailActivity({ email }: { email: TransactionalEmailLogDetailApi }): JSX.Element {
    const { person, personLoading, personFailed, activity, activityLoading, activityFailed } = useValues(
        transactionalEmailLogEntryLogic
    )
    const { loadActivity, loadPerson } = useActions(transactionalEmailLogEntryLogic)

    const firstName = person?.properties?.name ? String(person.properties.name).split(' ')[0] : null
    const title = firstName ? `What ${firstName} did around this email` : 'Activity around this email'

    let content: JSX.Element
    if (!email.distinct_id) {
        content = (
            <p className="text-sm text-secondary m-0">
                This send has no person attached. Pass a <code>distinct_id</code> when you send, and the person's
                activity before and after the email shows up here.
            </p>
        )
    } else if (personFailed && !personLoading) {
        const distinctId = email.distinct_id
        content = (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadPerson(distinctId),
                    'data-attr': 'transactional-email-person-retry',
                }}
            >
                The person behind this send couldn't load. Check your connection and try again.
            </LemonBanner>
        )
    } else if (person === null) {
        content = (
            <p className="text-sm text-secondary m-0">
                No events from this person yet. Once your app captures events for them, what they did before and after
                the email shows up here.
            </p>
        )
    } else if (activityFailed && !activityLoading && person) {
        content = (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadActivity({ personId: person.id, sentAt: email.created_at }),
                    'data-attr': 'transactional-email-activity-retry',
                }}
            >
                The activity couldn't load. Check your connection and try again.
            </LemonBanner>
        )
    } else if (!activity || activityLoading || personLoading) {
        content = (
            <div className="flex flex-col gap-3">
                {Array.from({ length: 6 }).map((_, index) => (
                    <LemonSkeleton key={index} className="h-5" />
                ))}
            </div>
        )
    } else {
        content = <TransactionalEmailActivityTimeline email={email} activity={activity} />
    }

    return (
        <section className="ph-no-capture border rounded bg-surface-primary p-4 flex flex-col gap-3">
            <div className="flex flex-col gap-0.5">
                <h3 className="text-base font-semibold m-0">{title}</h3>
                <p className="text-xs text-secondary m-0">
                    The person's events in your product, with this email's delivery and engagement in between.
                </p>
            </div>
            {content}
        </section>
    )
}
