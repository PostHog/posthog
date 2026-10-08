import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { supportsMarketingCrossSell } from 'lib/marketingCrossSell'
import { teamLogic } from 'scenes/teamLogic'
import { SourceTab, TileId } from 'scenes/web-analytics/common'
import { buildDataTableTileDataNodeLogicProps } from 'scenes/web-analytics/tiles/skeletons/useTileSkeletonLoading'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { NodeKind, WebStatsBreakdown } from '~/queries/schema/schema-general'

import { MarketingAnalyticsCrossSellCard } from './MarketingAnalyticsCrossSellCard'

export function MarketingAnalyticsCrossSell({ breakdown }: { breakdown: WebStatsBreakdown }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tiles, marketingCrossSellDismissed } = useValues(webAnalyticsLogic)
    const { dismissMarketingCrossSell } = useActions(webAnalyticsLogic)
    const { currentTeamId } = useValues(teamLogic)

    if (
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL] !== true ||
        marketingCrossSellDismissed ||
        !supportsMarketingCrossSell(breakdown)
    ) {
        return null
    }
    const sources = tiles.find((tile) => tile.tileId === TileId.SOURCES)
    const channels = sources?.kind === 'tabs' ? sources.tabs.find((tab) => tab.id === SourceTab.CHANNEL) : undefined
    if (!channels || channels.query.kind !== NodeKind.DataTableNode || !currentTeamId) {
        return null
    }

    return (
        <MarketingAnalyticsCrossSellCard
            teamId={currentTeamId}
            breakdown={breakdown}
            channels={buildDataTableTileDataNodeLogicProps({
                query: channels.query,
                insightProps: channels.insightProps,
                context: { insightProps: channels.insightProps },
                uniqueKey: `WebAnalytics.${TileId.SOURCES}.${SourceTab.CHANNEL}`,
            })}
            onDismiss={dismissMarketingCrossSell}
        />
    )
}
