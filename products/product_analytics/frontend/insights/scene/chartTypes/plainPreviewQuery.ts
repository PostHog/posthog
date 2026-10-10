import type { InsightVizNode } from '~/queries/schema/schema-general'
import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

/** A preview tile is too small for a legend, value labels or a total, so it draws only the shape of the chart. */
export function plainPreviewQuery(node: InsightVizNode): InsightVizNode {
    if (!isTrendsQuery(node.source)) {
        return node
    }
    return {
        ...node,
        vizSpecificOptions: {
            ...node.vizSpecificOptions,
            [ChartDisplayType.ActionsPie]: {
                ...node.vizSpecificOptions?.[ChartDisplayType.ActionsPie],
                hideAggregation: true,
            },
        },
        source: {
            ...node.source,
            trendsFilter: {
                ...node.source.trendsFilter,
                showLegend: false,
                showValuesOnSeries: false,
                showLabelsOnSeries: false,
            },
        },
    }
}
