import { formatBreakdownLabel, getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import type { IndexedTrendResult } from 'scenes/trends/types'

import { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { CohortType } from '~/types'

import { humanizeSeriesLabel } from '../shared/humanizeSeriesLabel'

export interface AggregatedDisplayLabelDeps {
    stackBreakdowns: boolean
    breakdownFilter: BreakdownFilter | null | undefined
    cohorts: CohortType[] | undefined
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined
}

/** Category-axis label for a single band of the aggregated (Bar chart - Total value) chart. */
export function getAggregatedDisplayLabel(r: IndexedTrendResult, deps: AggregatedDisplayLabelDeps): string {
    if (deps.stackBreakdowns) {
        // Breakdown values within the band are distinguished by color and the tooltip.
        return getDisplayNameFromEntityFilter(r.action) ?? humanizeSeriesLabel(r.label)
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
    return getDisplayNameFromEntityFilter(r.action) ?? humanizeSeriesLabel(r.label)
}
