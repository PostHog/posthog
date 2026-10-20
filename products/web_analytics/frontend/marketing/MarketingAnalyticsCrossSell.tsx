import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { supportsMarketingCrossSell } from 'lib/marketingCrossSell'
import { teamLogic } from 'scenes/teamLogic'
import { SourceTab, TileId, WebAnalyticsTile } from 'scenes/web-analytics/common'
import { buildDataTableTileDataNodeLogicProps } from 'scenes/web-analytics/tiles/skeletons/useTileSkeletonLoading'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind, WebStatsBreakdown } from '~/queries/schema/schema-general'

import { MarketingAnalyticsCrossSellSlot } from './MarketingAnalyticsCrossSellSlot'
import { marketingCrossSellStateLogic } from './marketingCrossSellStateLogic'

function sourceTabDataNodeProps(tiles: WebAnalyticsTile[], sourceTab: SourceTab): DataNodeLogicProps | null {
    const sources = tiles.find((tile) => tile.tileId === TileId.SOURCES)
    const tab = sources?.kind === 'tabs' ? sources.tabs.find((tab) => tab.id === sourceTab) : undefined
    if (!tab || tab.query.kind !== NodeKind.DataTableNode) {
        return null
    }
    return buildDataTableTileDataNodeLogicProps({
        query: tab.query,
        insightProps: tab.insightProps,
        context: { insightProps: tab.insightProps },
        uniqueKey: `WebAnalytics.${TileId.SOURCES}.${sourceTab}`,
    })
}

export function MarketingAnalyticsCrossSell({ breakdown }: { breakdown: WebStatsBreakdown }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tiles, marketingCrossSellDismissed } = useValues(webAnalyticsLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { isSnoozed } = useValues(marketingCrossSellStateLogic({ teamId: currentTeamId ?? 0 }))

    if (
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL] !== true ||
        marketingCrossSellDismissed ||
        isSnoozed ||
        !supportsMarketingCrossSell(breakdown)
    ) {
        return null
    }
    const channels = sourceTabDataNodeProps(tiles, SourceTab.CHANNEL)
    const utmSources = sourceTabDataNodeProps(tiles, SourceTab.UTM_SOURCE)
    if (!channels || !utmSources || !currentTeamId) {
        return null
    }

    return (
        <MarketingAnalyticsCrossSellSlot
            teamId={currentTeamId}
            breakdown={breakdown}
            channels={channels}
            utmSources={utmSources}
        />
    )
}
