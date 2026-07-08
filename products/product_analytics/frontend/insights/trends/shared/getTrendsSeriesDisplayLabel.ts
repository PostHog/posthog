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
}

/** Legend/series label for a single trends result. The user's custom rename (`action.custom_name`,
 *  set via the series rename UI) wins over the raw event/action name; breakdown series resolve to
 *  their formatted breakdown value. The `action` is shared across a series' breakdown values, so the
 *  breakdown guard must come first — otherwise every breakdown band would collapse onto one label. */
export function getTrendsSeriesDisplayLabel(r: IndexedTrendResult, deps: TrendsSeriesLabelDeps): string {
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
    return getDisplayNameFromEntityFilter(r.action) ?? humanizeSeriesLabel(r.label)
}
