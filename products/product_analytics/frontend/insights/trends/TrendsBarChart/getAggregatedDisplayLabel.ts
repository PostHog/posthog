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
    /** `trendsFilter.showSeriesNameWithBreakdown`. Opt-in, so a saved insight keeps its labels. */
    showSeriesNameWithBreakdown?: boolean | null
    /** Suppresses the series-name prefix, which carries no information when the query defines one
     *  series: every band would take the same prefix. */
    isSingleSeriesDefinition?: boolean
}

/** Category-axis label for a single band of the aggregated (Bar chart - Total value) chart. */
export function getAggregatedDisplayLabel(r: IndexedTrendResult, deps: AggregatedDisplayLabelDeps): string {
    if (deps.stackBreakdowns) {
        // Breakdown values within the band are distinguished by color and the tooltip.
        return getDisplayNameFromEntityFilter(r.action) ?? humanizeSeriesLabel(r.label)
    }
    if (r.breakdown_value != null) {
        const breakdownLabel = formatBreakdownLabel(
            r.breakdown_value,
            deps.breakdownFilter,
            deps.cohorts,
            deps.formatPropertyValueForDisplay,
            undefined,
            r.label
        )
        if (!deps.showSeriesNameWithBreakdown || deps.isSingleSeriesDefinition) {
            return breakdownLabel
        }
        // Only an entity name is used as the prefix, with no fallback to `r.label`: on a
        // multi-series breakdown the backend already sets `label` to "<series> - <breakdown>", so
        // falling back to it would repeat the breakdown value inside the prefix.
        const seriesName = getDisplayNameFromEntityFilter(r.action)
        return seriesName ? `${seriesName}: ${breakdownLabel}` : breakdownLabel
    }
    // Custom name wins over the event name, matching the legacy LineGraph y-axis. Series sharing
    // an event are differentiated only by their custom name, so falling back to the event name
    // would collapse them all onto the same label.
    return getDisplayNameFromEntityFilter(r.action) ?? humanizeSeriesLabel(r.label)
}
