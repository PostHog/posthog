import { formatBreakdownLabel, getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import type { IndexedTrendResult } from 'scenes/trends/types'

import type { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { CohortType } from '~/types'

import { humanizeSeriesLabel } from './humanizeSeriesLabel'

export interface TrendsSeriesLabelDeps {
    breakdownFilter: BreakdownFilter | null | undefined
    cohorts: CohortType[] | undefined
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined
    /** `trendsFilter.showSeriesNameWithBreakdown`. Opt-in, so a saved insight keeps its labels. */
    showSeriesNameWithBreakdown?: boolean | null
    /** Suppresses the series-name prefix, which carries no information when the query defines one
     *  series: every breakdown band would take the same prefix. */
    isSingleSeriesDefinition?: boolean
}

/** Legend/series label for a single trends result. The user's custom rename (`action.custom_name`,
 *  set via the series rename UI) wins over the raw event/action name; breakdown series resolve to
 *  their formatted breakdown value. The `action` is shared across a series' breakdown values, so the
 *  breakdown guard must come first — otherwise every breakdown band would collapse onto one label.
 *  `showSeriesNameWithBreakdown` opts a breakdown series into carrying both, as "<series>: <breakdown>",
 *  which is the only way to tell two series apart when they share a breakdown value. */
export function getTrendsSeriesDisplayLabel(r: IndexedTrendResult, deps: TrendsSeriesLabelDeps): string {
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
    return getDisplayNameFromEntityFilter(r.action) ?? humanizeSeriesLabel(r.label)
}
