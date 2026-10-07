import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { firstRunEngagementEventsLogic } from './firstRunEngagementEventsLogic'

export function EnableEngagementEventsAction(): JSX.Element | null {
    const { offerEngagementEvents, currentTeamLoading } = useValues(firstRunEngagementEventsLogic)
    const { enableEngagementEvents } = useActions(firstRunEngagementEventsLogic)

    if (!offerEngagementEvents) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <span className="font-normal">
                Turn on engagement events to record each email sent and delivered as a PostHog event for insights and
                funnels.
            </span>
            <LemonButton
                type="secondary"
                size="xsmall"
                loading={currentTeamLoading}
                onClick={enableEngagementEvents}
                data-attr="workflows-first-run-enable-engagement-events"
            >
                Enable engagement events
            </LemonButton>
        </div>
    )
}
