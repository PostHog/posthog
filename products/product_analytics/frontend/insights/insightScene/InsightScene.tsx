import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { isBIVisualizationNode, isDataVisualizationNode } from '~/queries/schema/node-guards'
import { ProductKey } from '~/queries/schema/schema-general'
import { ItemMode } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'
import { InsightAsScene } from 'products/product_analytics/frontend/insights/insightScene/InsightAsScene'
import { InsightSkeleton } from 'products/product_analytics/frontend/insights/insightScene/InsightSkeleton'

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightLoading, insightMode, dashboardId } = useValues(insightSceneLogic)

    useAttachedContext(
        insight?.short_id && insight?.query
            ? [{ type: 'insight', key: insight.short_id, label: insight.name || insight.derived_name || undefined }]
            : null
    )

    useEffect(() => {
        if (
            insightId &&
            insightId !== 'new' &&
            isDataVisualizationNode(insight?.query) &&
            insightMode === ItemMode.Edit
        ) {
            const editorUrl = isBIVisualizationNode(insight.query) ? urls.businessIntelligence : urls.sqlEditor
            router.actions.push(
                editorUrl({
                    insightShortId: insightId,
                    dashboard: dashboardId ?? undefined,
                })
            )
        }
    }, [insightId, insight?.query, insightMode, dashboardId])

    if (
        insightId === 'new' ||
        insightId?.startsWith('new-') ||
        (insightId &&
            insight?.id &&
            insight?.short_id &&
            (!isDataVisualizationNode(insight.query) || insightMode !== ItemMode.Edit))
    ) {
        return <InsightAsScene insightId={insightId} attachTo={insightSceneLogic} />
    }

    if (insightLoading) {
        return <InsightSkeleton />
    }

    return <NotFound object="insight" />
}

export const scene: SceneExport = {
    component: InsightScene,
    logic: insightSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}
