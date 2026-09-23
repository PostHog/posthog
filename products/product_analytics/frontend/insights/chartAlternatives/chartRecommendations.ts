import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { DISPLAY_TYPES_TO_CATEGORIES, NON_BREAKDOWN_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'
import { isPropertyValueMath } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/mathUtils'

import type { BreakdownFilter, TrendsQuery } from '~/queries/schema/schema-general'
import { hasBreakdownFilter } from '~/queries/utils'
import { ChartDisplayCategory, ChartDisplayType, PropertyMathType } from '~/types'
import type { AnyPropertyFilter } from '~/types'

import { breakdownProperties, isCountryProperty } from './chartDisplayOptions'
import type { ChartDisplayOption, ChartDisplayOptionGroup } from './chartDisplayOptions'

const DEFAULT_RECOMMENDATION_ORDER = [
    ChartDisplayType.Metric,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsDonut,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.BoxPlot,
    ChartDisplayType.WorldMap,
]

// Vertical bars get crowded once every bucket holds one bar per breakdown value.
const BREAKDOWN_DEMOTED_DISPLAYS = [ChartDisplayType.ActionsUnstackedBar, ChartDisplayType.ActionsBar]

function isSingleCountryBreakdown(breakdownFilter?: BreakdownFilter | null): boolean {
    const properties = breakdownProperties(breakdownFilter)
    return properties.length === 1 && isCountryProperty(properties[0])
}

function hasCountryContext(query: TrendsQuery): boolean {
    if (isSingleCountryBreakdown(query.breakdownFilter)) {
        return true
    }
    const filters: AnyPropertyFilter[] = [
        ...(convertPropertyGroupToProperties(query.properties) ?? []),
        ...(query.series ?? []).flatMap((node) => node.properties ?? []),
    ]
    return filters.some((filter) => isCountryProperty(filter.key))
}

function isStatistical(query: TrendsQuery): boolean {
    return (
        (query.series ?? []).some((node) => isPropertyValueMath(node.math) && node.math !== PropertyMathType.Sum) ||
        (query.trendsFilter?.smoothingIntervals ?? 1) > 1
    )
}

function rankRecommendations(query: TrendsQuery | null, currentDisplay: ChartDisplayType): ChartDisplayType[] {
    const boosted: ChartDisplayType[] = []
    const demoted = query && hasBreakdownFilter(query.breakdownFilter) ? BREAKDOWN_DEMOTED_DISPLAYS : []
    if (query) {
        if (hasCountryContext(query)) {
            boosted.push(ChartDisplayType.WorldMap)
        }
        if (isStatistical(query)) {
            boosted.push(ChartDisplayType.BoxPlot)
        }
    }
    if (DISPLAY_TYPES_TO_CATEGORIES[currentDisplay] === ChartDisplayCategory.TotalValue) {
        boosted.push(...PIE_DISPLAY_TYPES, ChartDisplayType.ActionsBarValue)
    }
    const ranked = [...new Set([...boosted, ...DEFAULT_RECOMMENDATION_ORDER])]
    return [...ranked.filter((display) => !demoted.includes(display)), ...demoted]
}

export function getChartAlternatives(
    options: ChartDisplayOptionGroup[] | null | undefined,
    query: TrendsQuery | null
): ChartDisplayOption[] {
    const optionsByDisplay = new Map(
        (options ?? []).flatMap((group) => group.options).map((option) => [option.display, option])
    )
    const currentDisplay = query?.trendsFilter?.display ?? ChartDisplayType.ActionsLineGraph
    const hasBreakdown = hasBreakdownFilter(query?.breakdownFilter)
    return rankRecommendations(query, currentDisplay)
        .filter((recommended) => !hasBreakdown || !NON_BREAKDOWN_DISPLAY_TYPES.includes(recommended))
        .map((recommended) => optionsByDisplay.get(recommended))
        .filter(
            (option): option is ChartDisplayOption =>
                !!option && option.display !== currentDisplay && !option.disabledReason
        )
        .slice(0, 3)
}
