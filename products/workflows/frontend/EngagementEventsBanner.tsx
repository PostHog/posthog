import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from '@posthog/lemon-ui'

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
            // pinned: localStorage key, renaming shows the banner again to everyone who dismissed it
            dismissKey={`workflows-engagement-events-banner-${currentTeam.id}`}
            onClose={() => {
                // pinned: analytics event name
                posthog.capture('workflows engagement events banner dismissed')
            }}
            action={{
                children: 'Turn off engagement events',
                loading: currentTeamLoading,
                'data-attr': 'workflows-engagement-events-banner-turn-off',
                onClick: () => {
                    // pinned: analytics event name
                    posthog.capture('workflows engagement events banner turned off')
                    updateCurrentTeam({
                        workflows_config: {
                            ...currentTeam.workflows_config,
                            capture_workflows_engagement_events: false,
                        },
                    })
                },
            }}
        >
            This project captures email sends, opens, clicks and bounces as PostHog events, so you can use them in
            insights and funnels. These events count toward your event usage and are billed like any other event.
        </LemonBanner>
    )
}
