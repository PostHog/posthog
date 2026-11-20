import { isInsightVizNode, isTrendsQuery } from '~/queries/schema/node-guards'
import type { CompareFilter, Node } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { readsOnlyWarehouseTables } from './rangeReachesBefore'

export interface RetentionDeletionChart {
    isStickiness: boolean
    querySource: Node | null | undefined
    compareFilter: CompareFilter | null | undefined
}

const SHADED_DISPLAYS = new Set<ChartDisplayType | undefined>([
    undefined,
    ChartDisplayType.Auto,
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsStackedBar,
])

export function showsRetentionDeletion({ isStickiness, querySource, compareFilter }: RetentionDeletionChart): boolean {
    return !isStickiness && !readsOnlyWarehouseTables(querySource) && !compareFilter?.compare
}

export function shadesRetentionDeletion(query: Node | null | undefined): boolean {
    const source = isInsightVizNode(query) ? query.source : undefined
    return (
        isTrendsQuery(source) &&
        SHADED_DISPLAYS.has(source.trendsFilter?.display) &&
        showsRetentionDeletion({ isStickiness: false, querySource: source, compareFilter: source.compareFilter })
    )
}
