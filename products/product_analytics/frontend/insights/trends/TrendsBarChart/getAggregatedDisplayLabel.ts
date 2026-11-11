import { formatBreakdownLabel } from 'scenes/insights/utils'
import { ActionNames, getResultSeries } from 'scenes/insights/utils/resultSeries'

import { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter, InsightQueryNode } from '~/queries/schema/schema-general'
import { CohortType } from '~/types'

import { getResultSeriesName } from 'products/product_analytics/frontend/insights/shared/resultSeriesName'
import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { humanizeSeriesLabel } from '../shared/humanizeSeriesLabel'

export interface AggregatedDisplayLabelDeps {
    querySource: InsightQueryNode | null | undefined
    actionNames?: ActionNames
    stackBreakdowns: boolean
    breakdownFilter: BreakdownFilter | null | undefined
    cohorts: CohortType[] | undefined
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined
}

/** Category-axis label for a single band of the aggregated (Bar chart - Total value) chart. */
export function getAggregatedDisplayLabel(r: IndexedTrendResult, deps: AggregatedDisplayLabelDeps): string {
    const seriesName = getResultSeriesName(getResultSeries(deps.querySource, r, deps.actionNames))
    if (deps.stackBreakdowns) {
        // Breakdown values within the band are distinguished by color and the tooltip.
        return seriesName ?? humanizeSeriesLabel(r.label)
    }
    if (r.breakdown_value != null) {
        return formatBreakdownLabel(
            r.breakdown_value,
            deps.breakdownFilter,
            deps.cohorts,
            deps.formatPropertyValueForDisplay,
            undefined,
            r.label
        )
    }
    // Custom name wins over the event name, matching the legacy LineGraph y-axis. Series sharing
    // an event are differentiated only by their custom name, so falling back to the event name
    // would collapse them all onto the same label.
    return seriesName ?? humanizeSeriesLabel(r.label)
}
