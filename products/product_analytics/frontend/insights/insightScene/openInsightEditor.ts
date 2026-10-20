import { combineUrl, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { Node } from '~/queries/schema/schema-general'
import { isBIVisualizationNode, isDataVisualizationNode } from '~/queries/utils'
import { DashboardType, InsightShortId } from '~/types'

export function openInsightEditor({
    query,
    insightShortId,
    dashboardId,
    queryChanged,
    enterEditMode,
}: {
    query: Node | null
    insightShortId: InsightShortId | undefined
    dashboardId: DashboardType['id'] | null
    queryChanged: boolean
    enterEditMode: () => void
}): void {
    if (isDataVisualizationNode(query) && insightShortId) {
        const editorUrl = isBIVisualizationNode(query) ? urls.businessIntelligence : urls.sqlEditor
        router.actions.push(
            editorUrl({
                insightShortId,
                dashboard: dashboardId ?? undefined,
                // Carry unsaved view-mode filter edits into the editor so they can be saved
                filters: queryChanged ? query.source.filters : undefined,
            })
        )
    } else if (insightShortId) {
        const editUrl = combineUrl(
            urls.insightEdit(insightShortId),
            dashboardId ? { dashboard: dashboardId } : {},
            // Carry unsaved view-mode filter edits into the editor so they can be saved
            queryChanged ? { q: JSON.stringify(query) } : {}
        ).url
        router.actions.push(editUrl)
    } else {
        enterEditMode()
    }
}
