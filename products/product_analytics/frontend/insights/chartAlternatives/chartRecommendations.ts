import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { DISPLAY_TYPES_TO_CATEGORIES, NON_BREAKDOWN_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'
import { isPropertyValueMath } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/mathUtils'

import type { BreakdownFilter, TrendsQuery } from '~/queries/schema/schema-general'
import { hasBreakdownFilter } from '~/queries/utils'
import { ChartDisplayCategory, ChartDisplayType, PropertyMathType } from '~/types'
import type { AnyPropertyFilter } from '~/types'

import { breakdownProperties, hasTrendsFormula, isCountryProperty } from './chartDisplayOptions'
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

// A breakdown reads best as parts of a whole; one line or one side-by-side bar per value gets crowded.
const BREAKDOWN_BOOSTED_DISPLAYS = [
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsDonut,
]
const BREAKDOWN_DEMOTED_DISPLAYS = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsUnstackedBar,
]

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

// Proportion charts need parts to compare: a breakdown, or several series that a formula does not collapse.
function hasMultipleParts(query: TrendsQuery): boolean {
    if (hasBreakdownFilter(query.breakdownFilter)) {
        return true
    }
    const trendsFilter = query.trendsFilter
    if (hasTrendsFormula(trendsFilter)) {
        // The query runner reads formulaNodes first, then the legacy formulas list, then the single formula.
        return (trendsFilter?.formulaNodes?.length || trendsFilter?.formulas?.length || 1) > 1
    }
    return (query.series?.length ?? 0) > 1
}

// A two-bucket range is what the slope graph draws, but only lead with it when its preview can be derived
// (the same rule as the slope recipe), so the gallery never opens on a blank suggested tile.
export function isTwoBucketSlopeCandidate(
    query: TrendsQuery | null,
    insightData: Record<string, any> | null | undefined
): boolean {
    if (!query) {
        return false
    }
    const first = insightData?.result?.[0] ?? insightData?.results?.[0]
    const twoBuckets = Array.isArray(first?.days) && first.days.length === 2
    const smoothed = (query.trendsFilter?.smoothingIntervals ?? 1) > 1
    const truncatedBreakdown = hasBreakdownFilter(query.breakdownFilter) && insightData?.hasMore !== false
    return twoBuckets && !smoothed && !truncatedBreakdown
}

function rankRecommendations(
    query: TrendsQuery | null,
    currentDisplay: ChartDisplayType,
    suggestSlope: boolean
): ChartDisplayType[] {
    const boosted: ChartDisplayType[] = []
    const hasBreakdown = !!query && hasBreakdownFilter(query.breakdownFilter)
    const demoted = hasBreakdown ? BREAKDOWN_DEMOTED_DISPLAYS : []
    if (suggestSlope) {
        boosted.push(ChartDisplayType.SlopeGraph)
    }
    if (query) {
        if (hasCountryContext(query)) {
            boosted.push(ChartDisplayType.WorldMap)
        }
        if (isStatistical(query)) {
            boosted.push(ChartDisplayType.BoxPlot)
        }
        if (hasBreakdown) {
            boosted.push(...BREAKDOWN_BOOSTED_DISPLAYS)
        }
        if (
            DISPLAY_TYPES_TO_CATEGORIES[currentDisplay] === ChartDisplayCategory.TotalValue &&
            hasMultipleParts(query)
        ) {
            boosted.push(...PIE_DISPLAY_TYPES, ChartDisplayType.ActionsBarValue)
        }
    }
    const ranked = [...new Set([...boosted, ...DEFAULT_RECOMMENDATION_ORDER])]
    return [...ranked.filter((display) => !demoted.includes(display)), ...demoted]
}

export function getChartAlternatives(
    options: ChartDisplayOptionGroup[] | null | undefined,
    query: TrendsQuery | null,
    suggestSlope = false
): ChartDisplayOption[] {
    const optionsByDisplay = new Map(
        (options ?? []).flatMap((group) => group.options).map((option) => [option.display, option])
    )
    const currentDisplay = query?.trendsFilter?.display ?? ChartDisplayType.ActionsLineGraph
    const hasBreakdown = hasBreakdownFilter(query?.breakdownFilter)
    return rankRecommendations(query, currentDisplay, suggestSlope)
        .filter((recommended) => !hasBreakdown || !NON_BREAKDOWN_DISPLAY_TYPES.includes(recommended))
        .map((recommended) => optionsByDisplay.get(recommended))
        .filter(
            (option): option is ChartDisplayOption =>
                !!option && option.display !== currentDisplay && !option.disabledReason
        )
        .slice(0, 3)
}
