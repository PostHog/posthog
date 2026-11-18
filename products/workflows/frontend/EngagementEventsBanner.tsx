import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from '@posthog/lemon-ui'

import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

export function EngagementEventsBanner(): JSX.Element | null {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    if (!currentTeam?.workflows_config?.capture_workflows_engagement_events) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            dismissKey={`workflows-engagement-events-banner-${currentTeam.id}`}
            onClose={() => {
                posthog.capture('workflows engagement events banner dismissed')
            }}
            action={{
                children: 'Turn off engagement events',
                loading: currentTeamLoading,
                disabledReason:
                    (currentTeam.effective_membership_level ?? -1) < TeamMembershipLevel.Admin
                        ? 'Only project admins can turn off engagement events'
                        : undefined,
                'data-attr': 'workflows-engagement-events-banner-turn-off',
                onClick: () => {
                    posthog.capture('workflows engagement events banner turned off')
                    updateCurrentTeam({ workflows_config: { capture_workflows_engagement_events: false } })
                },
            }}
        >
            This project captures email sends, opens, clicks and bounces as PostHog events, so you can use them in
            insights and funnels. These events count toward your event usage and are billed like any other event.
        </LemonBanner>
    )
}
