import { useActions, useValues } from 'kea'

import { IconDashboard } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { audienceEngagementLogic } from './audienceEngagementLogic'
import { AudienceEngagementTileCard } from './AudienceEngagementTileCard'
import { AUDIENCE_ENGAGEMENT_TILES } from './audienceEngagementTiles'
import { EmailMetricsTotalsCard } from './EmailMetricsTotalsCard'
import { TurnOnEngagementEvents } from './TurnOnEngagementEvents'

export function AudienceEngagement(): JSX.Element {
    const { engagementEventsCaptured, createdDashboardLoading } = useValues(audienceEngagementLogic)
    const { createDashboard } = useActions(audienceEngagementLogic)

    if (!engagementEventsCaptured) {
        return (
            <div className="flex flex-col gap-4 max-w-3xl" data-attr="audience-engagement-without-events">
                <EmailMetricsTotalsCard />
                <TurnOnEngagementEvents surface="engagement" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4" data-attr="audience-engagement">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="text-secondary m-0 max-w-2xl">
                    Engagement events from every workflow and broadcast in the last 30 days. Open a chart as an insight
                    to change it, or create a dashboard you can edit and share.
                </p>
                <LemonButton
                    type="primary"
                    icon={<IconDashboard />}
                    loading={createdDashboardLoading}
                    onClick={() => createDashboard()}
                    data-attr="audience-engagement-create-dashboard"
                >
                    Create dashboard from this
                </LemonButton>
            </div>
            <div className="grid grid-cols-1 gap-4 @min-[64rem]/main-content:grid-cols-2">
                {AUDIENCE_ENGAGEMENT_TILES.map((tile) => (
                    <AudienceEngagementTileCard key={tile.key} tile={tile} />
                ))}
            </div>
        </div>
    )
}
