import clsx from 'clsx'
import { BindLogic, BuiltLogic, Logic, LogicWrapper, useActions, useMountedLogic, useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'
import { containsHogQLQuery, isBIVisualizationNode, isDataVisualizationNode, isInsightVizNode } from '~/queries/utils'
import { InsightShortId, ItemMode } from '~/types'

import { insightDataChecksLogic } from 'products/product_analytics/frontend/insights/dataChecks/insightDataChecksLogic'
import { InsightHomeGuide } from 'products/product_analytics/frontend/insights/home/InsightHomeGuide'
import { InsightModals } from 'products/product_analytics/frontend/insights/insightScene/InsightModals'
import { SubscriptionSummaries } from 'products/subscriptions/frontend/components/SubscriptionSummaries/SubscriptionSummaries'

import { InsightFlagCalledBanner } from './banners/InsightFlagCalledBanner'
import { InsightQueryScanBanner } from './banners/InsightQueryScanBanner'
import { InsightRetentionBanner } from './banners/InsightRetentionBanner'
import { InsightWarehouseSyncBanner } from './banners/InsightWarehouseSyncBanner'
import { InsightSceneHeader } from './InsightSceneHeader'
import { SqlInsightFilters } from './SqlInsightFilters'

export interface InsightAsSceneProps {
    insightId: InsightShortId | 'new'
    attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>
}

export function InsightAsScene({ insightId, attachTo }: InsightAsSceneProps): JSX.Element | null {
    // insightSceneLogic
    const { insightMode, insight, filtersOverride, variablesOverride, hasOverrides, dashboardId } =
        useValues(insightSceneLogic)
    const { currentTeamId } = useValues(teamLogic)

    // insightLogic
    const logic = insightLogic({
        dashboardItemId: insightId || 'new',
        dashboardId: dashboardId ?? undefined,
        // don't use cached insight if we have overrides
        cachedInsight: hasOverrides && insight?.short_id === insightId ? insight : null,
        filtersOverride,
        variablesOverride,
    })
    const { insightProps, accessDeniedToInsight, insightLoading } = useValues(logic)

    // insightDataLogic
    const { query, showQueryEditor } = useValues(insightDataLogic(insightProps))
    const { setQuery: setInsightQuery } = useActions(insightDataLogic(insightProps))
    const { zoomDateRange } = useActions(insightVizDataLogic(insightProps))

    useFileSystemLogView({
        type: 'insight',
        ref: insight?.short_id,
        enabled: Boolean(currentTeamId && insight?.short_id && insight?.saved && !accessDeniedToInsight),
    })

    // other logics
    useAttachedLogic(logic, attachTo) // insightLogic(insightProps)
    useAttachedLogic(insightDataLogic(insightProps), attachTo)
    // Mounted here and not in the mark, so a check result survives while the chart reloads and hides the mark.
    useMountedLogic(insightDataChecksLogic(insightProps))

    const actuallyShowQueryEditor = insightMode === ItemMode.Edit && showQueryEditor

    const setQuery = (q: Node | ((q: Node) => Node), isSourceUpdate?: boolean): void => {
        let node = typeof q === 'function' ? (query ? q(query) : null) : q
        if (!isInsightVizNode(node) || isSourceUpdate) {
            setInsightQuery(node)
        }
    }

    if (accessDeniedToInsight) {
        return <AccessDenied object="insight" />
    }

    if (!insight?.query) {
        return null
    }

    const isEditing = insightMode === ItemMode.Edit

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightModals insightLogicProps={insightProps} />
            <SceneContent className={clsx('Insight', isEditing && '!gap-0')}>
                {isEditing ? (
                    <div className="flex flex-col gap-y-4 shrink-0">
                        <InsightSceneHeader insightLogicProps={insightProps} />
                    </div>
                ) : (
                    <InsightSceneHeader insightLogicProps={insightProps} />
                )}

                {insightId === 'new' && isEditing && <InsightHomeGuide query={query} />}

                <InsightRetentionBanner insightProps={insightProps} />

                <InsightFlagCalledBanner insightProps={insightProps} />

                {!isBIVisualizationNode(query) && <InsightQueryScanBanner insightProps={insightProps} />}

                <InsightWarehouseSyncBanner insightProps={insightProps} />

                {!isEditing && !!insight.id && <SubscriptionSummaries insightId={insight.id} />}

                <SqlInsightFilters query={query} setQuery={setQuery}>
                    {isDataVisualizationNode(query) && insightLoading ? (
                        // Avoid painting the stale chart type during a reload (the query re-syncs in insightDataLogic).
                        <LemonSkeleton className="h-100 w-full" />
                    ) : (
                        <Query
                            attachTo={attachTo}
                            query={isInsightVizNode(query) ? { ...query, full: true } : query}
                            setQuery={setQuery}
                            readOnly={insightMode !== ItemMode.Edit}
                            editMode={insightMode === ItemMode.Edit}
                            context={{
                                showOpenEditorButton: false,
                                showQueryEditor: actuallyShowQueryEditor,
                                showQueryHelp: insightMode === ItemMode.Edit && !containsHogQLQuery(query),
                                showDataChecks: true,
                                insightProps,
                                // Flag-gated inside the charts' shared useDateRangeZoom hook.
                                onDateRangeZoom: zoomDateRange,
                            }}
                            filtersOverride={filtersOverride}
                            variablesOverride={variablesOverride}
                        />
                    )}
                </SqlInsightFilters>
            </SceneContent>
        </BindLogic>
    )
}
