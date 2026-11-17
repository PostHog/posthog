import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function EmailEngagementEventsNotice(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (currentTeam?.workflows_config?.capture_workflows_engagement_events) {
        return (
            <div className="flex items-center gap-1.5 mt-2 text-xs text-muted-alt">
                <IconCheck className="text-success text-base" />
                <span>Email engagement is being captured as PostHog events.</span>
                <Link to={urls.settings('environment-workflows', 'workflows-engagement-events')} target="_blank">
                    Manage in settings
                </Link>
            </div>
        )
    }

    const disabledReason =
        restrictedReason && isAuthenticatedTeam(currentTeam)
            ? 'Ask a project admin to turn on engagement events.'
            : restrictedReason

    return (
        <LemonBanner type="info" hideIcon className="mt-2">
            <div className="flex flex-col gap-2">
                <span className="text-xs">
                    Email engagement (sends, opens, clicks, bounces) is recorded as workflow metrics. You can also
                    capture these as standard PostHog events for use in insights and funnels. They count toward your
                    event usage and are billed like any other event.
                </span>
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        loading={currentTeamLoading}
                        disabledReason={disabledReason}
                        onClick={() =>
                            updateCurrentTeam({
                                workflows_config: {
                                    ...currentTeam?.workflows_config,
                                    capture_workflows_engagement_events: true,
                                },
                            })
                        }
                    >
                        Enable engagement events
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        to={urls.settings('environment-workflows', 'workflows-engagement-events')}
                        targetBlank
                    >
                        Manage in settings
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        to="https://posthog.com/docs/workflows/engagement-events"
                        targetBlank
                    >
                        Learn more
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
