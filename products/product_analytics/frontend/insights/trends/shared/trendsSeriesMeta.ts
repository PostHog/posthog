import { ActionNames, ResultSeries, getResultSeries } from 'scenes/insights/utils/resultSeries'

import type { Noun } from '~/models/groupsModel'
import type { InsightQueryNode } from '~/queries/schema/schema-general'

import type { SeriesDatum } from 'products/product_analytics/frontend/insights/shared/InsightTooltip/insightTooltipUtils'
import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

export type TrendsSeriesMeta = {
    series: ResultSeries
    /** Series name for results without a series node — formula results carry their formula label here. */
    series_name?: string
    breakdown_value?: string | number | string[]
    compare_label?: SeriesDatum['compare_label']
    days?: string[]
    order?: number
}

export const buildTrendsSeriesMeta = (
    r: IndexedTrendResult,
    querySource: InsightQueryNode | null | undefined,
    actionNames?: ActionNames
): TrendsSeriesMeta => {
    const series = getResultSeries(querySource, r, actionNames)
    return {
        series,
        // Formula results have no series node; their raw label (custom name or "Formula (…)") is the
        // only series name available for tooltip attribution.
        series_name: series.node ? undefined : r.label,
        breakdown_value: r.breakdown_value,
        compare_label: r.compare_label,
        days: r.days,
        order: series.order,
    }
}

/** Resolve the `groupTypeLabel` shown by tooltips and persons-modal titles.
 *  `'people'` is the default; `'none'` suppresses the noun; anything else
 *  defers to the team's group-type plural. */
export function resolveGroupTypeLabel(
    labelGroupType: 'people' | 'none' | number,
    aggregationLabel: (groupTypeIndex: number | null | undefined) => Noun
): string {
    if (labelGroupType === 'people') {
        return 'people'
    }
    if (labelGroupType === 'none') {
        return ''
    }
    return aggregationLabel(labelGroupType).plural
}
