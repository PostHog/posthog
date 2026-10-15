import { useValues } from 'kea'

import { DebugCHQueries } from 'lib/components/Shortcuts/utils/DebugCHQueries'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { InsightLogicProps, ItemMode } from '~/types'

import { ReloadInsight } from 'products/product_analytics/frontend/insights/shared/ReloadInsight'

import { InsightDashboardFiltersBanner } from './InsightDashboardFiltersBanner'
import { InsightPageHeader } from './InsightPageHeader'
import { InsightsNav } from './InsightsNav'

export interface InsightSceneHeaderProps {
    insightLogicProps: InsightLogicProps
}

export function InsightSceneHeader({ insightLogicProps }: InsightSceneHeaderProps): JSX.Element {
    const { insightMode, hasOverrides, freshQuery, filtersOverride, variablesOverride, tileFiltersOverride } =
        useValues(insightSceneLogic)
    const { showDebugPanel } = useValues(insightDataLogic(insightLogicProps))
    const { insight, savedInsight } = useValues(insightLogic(insightLogicProps))
    const insightId = insightLogicProps.dashboardItemId

    return (
        <>
            <InsightPageHeader insightLogicProps={insightLogicProps} />

            {hasOverrides && insightId && (
                <InsightDashboardFiltersBanner
                    query={savedInsight.query ?? null}
                    insightId={insightId}
                    dashboardId={insightLogicProps.dashboardId}
                    filtersOverride={filtersOverride ?? undefined}
                    variablesOverride={variablesOverride ?? undefined}
                    tileFiltersOverride={tileFiltersOverride}
                />
            )}

            {insightMode === ItemMode.Edit && (
                <div className="[&_.LemonTabs]:![--lemon-tabs-margin-bottom:0]">
                    <InsightsNav />
                </div>
            )}

            {showDebugPanel && insight?.id && (
                <div className="mb-4">
                    <DebugCHQueries insightId={insight.id} />
                </div>
            )}

            {freshQuery ? <ReloadInsight /> : null}
        </>
    )
}
