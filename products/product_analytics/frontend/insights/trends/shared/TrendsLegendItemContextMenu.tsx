import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import { InsightLegendRowContextMenu } from 'lib/components/InsightLegend/InsightLegendRowContextMenu'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { InsightLogicProps } from '~/types'

interface TrendsLegendItemContextMenuProps {
    insightProps: InsightLogicProps
    item: IndexedTrendResult
    children: ReactNode
}

/** Right-click isolate/show-all/hide-all menu for a quill legend row, mirroring the legacy
 *  InsightLegendRow menu — shares trendsDataLogic's toggle actions so hidden state stays in
 *  the query (resultCustomizations). */
export function TrendsLegendItemContextMenu({
    insightProps,
    item,
    children,
}: TrendsLegendItemContextMenuProps): JSX.Element {
    const {
        getTrendsHidden,
        indexedResults,
        areAllSeriesVisible,
        showLegendIsolateSeriesItem,
        getIsOnlyVisibleSeriesInLegend,
    } = useValues(trendsDataLogic(insightProps))
    const { toggleOtherSeriesHidden, toggleAllResultsHidden } = useActions(trendsDataLogic(insightProps))

    const isHidden = getTrendsHidden(item)
    const isOnlyThisVisible = getIsOnlyVisibleSeriesInLegend(item)

    return (
        <InsightLegendRowContextMenu
            areAllSeriesVisible={areAllSeriesVisible}
            showLegendIsolateSeriesItem={showLegendIsolateSeriesItem}
            isHidden={isHidden}
            isOnlyThisVisible={isOnlyThisVisible}
            onToggleOtherSeries={() => {
                posthog.capture('insight_legend_context_menu', {
                    action: isOnlyThisVisible ? 'show_all_series' : 'hide_other_series',
                    source: 'isolate_row',
                    series_count: indexedResults.length,
                })
                toggleOtherSeriesHidden(item)
            }}
            onToggleAllSeries={() => {
                posthog.capture('insight_legend_context_menu', {
                    action: areAllSeriesVisible ? 'hide_all_series' : 'show_all_series',
                    source: 'toggle_all_row',
                    series_count: indexedResults.length,
                })
                toggleAllResultsHidden(indexedResults, areAllSeriesVisible)
            }}
        >
            {children}
        </InsightLegendRowContextMenu>
    )
}
