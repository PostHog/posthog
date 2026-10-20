import { toDisplayEntityFilter } from 'lib/components/EntityFilterInfo'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import type { ResultSeries } from 'scenes/insights/utils/resultSeries'

/**
 * The name a result row's series displays under, by the rules `EntityFilterInfo` applies to the same node. Null
 * on a row without a series node, such as a formula row, whose label is its name.
 */
export function getResultSeriesName(series: ResultSeries): string | null {
    return series.node ? getDisplayNameFromEntityFilter(toDisplayEntityFilter(series.node)) : null
}
