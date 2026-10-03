import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { engagementEventsLogic } from '../../../engagementEventsLogic'
import { TurnOnEngagementEvents } from '../../TurnOnEngagementEvents'
import { SetupStepCard } from '../SetupStepCard'

export function EngagementEventsStep(): JSX.Element {
    const { engagementEventsCaptured } = useValues(engagementEventsLogic)

    if (!engagementEventsCaptured) {
        return <TurnOnEngagementEvents surface="setup" />
    }

    return (
        <SetupStepCard
            title={
                <span className="flex items-center gap-1">
                    <IconCheckCircle className="text-success" />
                    Engagement events are on
                </span>
            }
            description="PostHog records an event when an email is sent, delivered, opened or clicked, when it bounces or is marked as spam, and when a recipient unsubscribes."
            dataAttr="audience-setup-engagement-events-on"
        >
            <div>
                <LemonButton
                    type="secondary"
                    to={urls.audience('engagement')}
                    data-attr="audience-setup-open-engagement"
                >
                    See engagement
                </LemonButton>
            </div>
        </SetupStepCard>
    )
}
