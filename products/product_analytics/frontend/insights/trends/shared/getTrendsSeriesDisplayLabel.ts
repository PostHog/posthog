import { formatBreakdownLabel, getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

import type { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { CohortType } from '~/types'

import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { humanizeSeriesLabel } from './humanizeSeriesLabel'

export interface TrendsSeriesLabelDeps {
    breakdownFilter: BreakdownFilter | null | undefined
    cohorts: CohortType[] | undefined
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined
    isSingleSeriesDefinition?: boolean
}

export function getTrendsSeriesDisplayLabel(r: IndexedTrendResult, deps: TrendsSeriesLabelDeps): string {
    const seriesName = getDisplayNameFromEntityFilter(r.action) ?? humanizeSeriesLabel(r.label)
    if (r.breakdown_value != null) {
        const breakdownLabel = formatBreakdownLabel(
            r.breakdown_value,
            deps.breakdownFilter,
            deps.cohorts,
            deps.formatPropertyValueForDisplay,
            undefined,
            r.label
        )
        return deps.isSingleSeriesDefinition ? breakdownLabel : `${seriesName} · ${breakdownLabel}`
    }
    return seriesName
}
