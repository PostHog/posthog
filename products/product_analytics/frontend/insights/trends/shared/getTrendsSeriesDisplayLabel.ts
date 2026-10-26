import { alphabet } from 'lib/utils/strings'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { getResultSeries } from 'scenes/insights/utils/resultSeries'

import type { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import type { BreakdownFilter, InsightQueryNode } from '~/queries/schema/schema-general'
import type { CohortType } from '~/types'

import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { getResultSeriesName } from '../../shared/resultSeriesName'
import type { SeriesIdentification } from '../../shared/seriesIdentification'
import { humanizeSeriesLabel } from './humanizeSeriesLabel'

export interface TrendsSeriesLabelDeps {
    querySource: InsightQueryNode | null | undefined
    breakdownFilter: BreakdownFilter | null | undefined
    cohorts: CohortType[] | undefined
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined
    isSingleSeriesDefinition?: boolean
    seriesIdentification?: SeriesIdentification
}

export function getTrendsSeriesDisplayLabel(r: IndexedTrendResult, deps: TrendsSeriesLabelDeps): string {
    const series = getResultSeries(deps.querySource, r)
    const seriesName = getResultSeriesName(series) ?? humanizeSeriesLabel(r.label)
    if (r.breakdown_value != null) {
        const breakdownLabel = formatBreakdownLabel(
            r.breakdown_value,
            deps.breakdownFilter,
            deps.cohorts,
            deps.formatPropertyValueForDisplay,
            undefined,
            r.label
        )
        if (deps.isSingleSeriesDefinition) {
            return breakdownLabel
        }
        const seriesPrefix =
            deps.seriesIdentification === 'letter-and-name' ? `${alphabet[series.order]} ${seriesName}` : seriesName
        return `${seriesPrefix} · ${breakdownLabel}`
    }
    return seriesName
}
