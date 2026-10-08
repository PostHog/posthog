import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { TurnOnEngagementEventsSurface, engagementEventsLogic } from '../engagementEventsLogic'

export function TurnOnEngagementEvents({ surface }: { surface: TurnOnEngagementEventsSurface }): JSX.Element {
    const { currentTeamLoading } = useValues(engagementEventsLogic)
    const { turnOnEngagementEvents } = useActions(engagementEventsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3" data-attr="audience-turn-on-engagement-events">
            <div className="flex flex-col gap-1">
                <h3 className="font-semibold m-0">Turn on engagement events</h3>
                <p className="m-0">
                    PostHog records an event in this project when an email is sent, delivered, opened or clicked, when
                    it bounces or is marked as spam, and when a recipient unsubscribes. Opens and clicks follow your
                    email tracking consent setting. These events count toward your event usage.
                </p>
            </div>
            <div>
                <LemonButton
                    type="primary"
                    loading={currentTeamLoading}
                    disabledReason={restrictedReason}
                    onClick={() => turnOnEngagementEvents(surface)}
                    data-attr="audience-turn-on-engagement-events-button"
                >
                    Turn on engagement events
                </LemonButton>
            </div>
        </LemonCard>
    )
}
