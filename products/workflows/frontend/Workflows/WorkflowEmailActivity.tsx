import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EmailActivityTimeline } from '../Transactional/log/EmailActivityTimeline'
import { WorkflowEmailActivityLogicProps, workflowEmailActivityLogic } from './workflowEmailActivityLogic'

function ActivitySkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            {Array.from({ length: 6 }).map((_, index) => (
                <LemonSkeleton key={index} className="h-5" />
            ))}
        </div>
    )
}

function NoEngagementEvents({ enabled }: { enabled: boolean }): JSX.Element {
    const settings = (
        <Link to={urls.settings('environment-workflows', 'workflows-engagement-events')} target="_blank">
            Capture email engagement events
        </Link>
    )
    return (
        <LemonBanner type="info">
            {enabled ? (
                <>
                    No engagement events were recorded for this email, so its activity isn't available. They're only
                    recorded while {settings} is on.
                </>
            ) : (
                <>Turn on {settings} to see what people do around the emails this workflow sends from now on.</>
            )}
        </LemonBanner>
    )
}

/** What the person did around one workflow email, on the same rail as transactional emails. */
export function WorkflowEmailActivity(props: WorkflowEmailActivityLogicProps): JSX.Element {
    const logic = workflowEmailActivityLogic(props)
    const {
        email,
        emailLoading,
        emailFailed,
        activity,
        activityLoading,
        activityFailed,
        beforeExpanded,
        afterExpanded,
    } = useValues(logic)
    const { loadEmail, loadActivity, showAllBefore, showAllAfter } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)

    if (emailFailed && !emailLoading) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadEmail(), 'data-attr': 'workflow-email-retry' }}
            >
                This email couldn't load. Check your connection and try again.
            </LemonBanner>
        )
    }
    if (email === undefined || emailLoading) {
        return <ActivitySkeleton />
    }
    if (email === null) {
        return <NoEngagementEvents enabled={!!currentTeam?.workflows_config?.capture_workflows_engagement_events} />
    }
    if (activityFailed && !activityLoading) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadActivity(),
                    'data-attr': 'workflow-email-activity-retry',
                }}
            >
                The activity couldn't load. Check your connection and try again.
            </LemonBanner>
        )
    }
    if (!activity || activityLoading) {
        return <ActivitySkeleton />
    }
    return (
        <div className="ph-no-capture">
            <EmailActivityTimeline
                email={{
                    status: email.status,
                    timeline: email.timeline,
                    created_at: email.sent_at,
                    template_name: email.subject,
                }}
                activity={activity}
                beforeExpanded={beforeExpanded}
                afterExpanded={afterExpanded}
                onShowEarlier={showAllBefore}
                onShowLater={showAllAfter}
            />
        </div>
    )
}
