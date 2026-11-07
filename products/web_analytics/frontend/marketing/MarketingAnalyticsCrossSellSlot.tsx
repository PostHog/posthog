import { useValues } from 'kea'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { WebStatsBreakdown } from '~/queries/schema/schema-general'

import { marketingAnalyticsCrossSellLogic } from './marketingAnalyticsCrossSellLogic'
import { MarketingAnalyticsPaidTrafficCard } from './MarketingAnalyticsPaidTrafficCard'

export interface MarketingAnalyticsCrossSellSlotProps {
    teamId: number
    breakdown: WebStatsBreakdown
    channels: DataNodeLogicProps
    utmSources: DataNodeLogicProps
}

export function MarketingAnalyticsCrossSellSlot({
    teamId,
    breakdown,
    channels,
    utmSources,
}: MarketingAnalyticsCrossSellSlotProps): JSX.Element | null {
    const { showCard } = useValues(marketingAnalyticsCrossSellLogic({ teamId, channels }))

    if (!showCard) {
        return null
    }
    return (
        <MarketingAnalyticsPaidTrafficCard
            teamId={teamId}
            channels={channels}
            utmSources={utmSources}
            breakdown={breakdown}
        />
    )
}
