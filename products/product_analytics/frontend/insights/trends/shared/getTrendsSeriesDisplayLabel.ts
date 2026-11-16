import { alphabet } from 'lib/utils/strings'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { ActionNames, getResultSeries } from 'scenes/insights/utils/resultSeries'

import type { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import type { BreakdownFilter, InsightQueryNode } from '~/queries/schema/schema-general'
import { CompareLabelType, type CohortType } from '~/types'

import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { getResultSeriesName } from '../../shared/resultSeriesName'
import type { SeriesIdentification } from '../../shared/seriesIdentification'
import { humanizeSeriesLabel } from './humanizeSeriesLabel'

export interface TrendsSeriesLabelDeps {
    querySource: InsightQueryNode | null | undefined
    actionNames?: ActionNames
    breakdownFilter: BreakdownFilter | null | undefined
    cohorts: CohortType[] | undefined
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined
    isSingleSeriesDefinition?: boolean
    seriesIdentification?: SeriesIdentification
}

export function getTrendsSeriesDisplayLabel(r: IndexedTrendResult, deps: TrendsSeriesLabelDeps): string {
    const label = getSeriesLabel(r, deps)
    // The previous period is the same series, so without the suffix both legend rows read the same
    return r.compare_label === CompareLabelType.Previous ? `${label} · Previous` : label
}

function getSeriesLabel(r: IndexedTrendResult, deps: TrendsSeriesLabelDeps): string {
    const series = getResultSeries(deps.querySource, r, deps.actionNames)
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
