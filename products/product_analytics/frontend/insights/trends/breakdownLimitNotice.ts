import { humanFriendlyNumber } from 'lib/utils/numbers'

import { TrendResult } from '~/types'

export function getBreakdownLimitNotice(results: TrendResult[], breakdownLimit: number): string {
    // Several formulas and a compared period repeat the same values, so count the current period's distinct values.
    const rankedResults = results.filter(
        (result) => result.breakdown_event_count != null && result.compare_label !== 'previous'
    )
    if (!rankedResults.length) {
        return `Breakdown limited to ${breakdownLimit} - more available`
    }

    const shownValuesCount = new Set(
        rankedResults
            .filter((result) => result.breakdown_other_values_count == null)
            .map((result) => JSON.stringify(result.breakdown_value))
    ).size
    const otherValuesCount = Math.max(0, ...rankedResults.map((result) => result.breakdown_other_values_count ?? 0))

    const limited = `Showing the ${humanFriendlyNumber(shownValuesCount)} breakdown ${
        shownValuesCount === 1 ? 'value' : 'values'
    } with the most events across all series.`
    if (otherValuesCount === 0) {
        return limited
    }
    return `${limited} ${humanFriendlyNumber(otherValuesCount)} more ${
        otherValuesCount === 1 ? 'is' : 'are'
    } grouped in Other.`
}
