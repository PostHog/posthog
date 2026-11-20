import { useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { DebugCHQueries } from 'lib/components/Shortcuts/utils/DebugCHQueries'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { urls } from 'scenes/urls'

import { InsightShortId, InsightLogicProps, ItemMode } from '~/types'

import { QuillInsightBanner } from 'products/product_analytics/frontend/insights/shared/QuillInsightBanner'
import { ReloadInsight } from 'products/product_analytics/frontend/insights/shared/ReloadInsight'

import { InsightPageHeader } from './InsightPageHeader'
import { InsightsNav } from './InsightsNav'

export interface InsightSceneHeaderProps {
    insightLogicProps: InsightLogicProps
}

export function InsightSceneHeader({ insightLogicProps }: InsightSceneHeaderProps): JSX.Element {
    const { insightMode, hasOverrides, freshQuery } = useValues(insightSceneLogic)
    const { showDebugPanel } = useValues(insightDataLogic(insightLogicProps))
    const { insight } = useValues(insightLogic(insightLogicProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const insightId = insightLogicProps.dashboardItemId
    const overridesMessage =
        "You're viewing this insight with a dashboard's filters applied, so it can't be edited. Discard the filters to edit the saved insight."

    return (
        <>
            <InsightPageHeader insightLogicProps={insightLogicProps} />

            {hasOverrides &&
                insightId &&
                (todayRailNav ? (
                    <QuillInsightBanner
                        tone="warning"
                        className="mb-4"
                        action={{
                            children: 'Discard overrides',
                            to: urls.insightView(insightId as InsightShortId, insightLogicProps.dashboardId),
                        }}
                    >
                        {overridesMessage}
                    </QuillInsightBanner>
                ) : (
                    <LemonBanner type="warning" className="mb-4">
                        <div className="flex flex-row items-center justify-between gap-2">
                            <span>{overridesMessage}</span>

                            <LemonButton
                                type="secondary"
                                to={urls.insightView(insightId as InsightShortId, insightLogicProps.dashboardId)}
                            >
                                Discard overrides
                            </LemonButton>
                        </div>
                    </LemonBanner>
                ))}

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
