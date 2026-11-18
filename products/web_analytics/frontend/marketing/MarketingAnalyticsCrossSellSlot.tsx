import { useValues } from 'kea'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { WebStatsBreakdown } from '~/queries/schema/schema-general'

import { MarketingAnalyticsCrossSellCard } from './MarketingAnalyticsCrossSellCard'
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
    const { cardVariant } = useValues(marketingAnalyticsCrossSellLogic({ teamId, channels }))

    if (cardVariant === 'contextual_card') {
        return <MarketingAnalyticsCrossSellCard teamId={teamId} channels={channels} breakdown={breakdown} />
    }
    if (cardVariant === 'quantified_card') {
        return (
            <MarketingAnalyticsPaidTrafficCard
                teamId={teamId}
                channels={channels}
                utmSources={utmSources}
                breakdown={breakdown}
            />
        )
    }
    return null
}
