import type { ObservationSearchResultApi } from '../generated/api.schemas'

export type Tier = 'top' | 'other'

export interface TierGroup {
    tier: Tier | null
    results: ObservationSearchResultApi[]
}

/** Splits one page of ranked results into contiguous tier groups, in order. One untiered group when there is no cutoff. */
export function groupByTier(results: ObservationSearchResultApi[], cutoff: number | null): TierGroup[] {
    if (cutoff === null) {
        return results.length > 0 ? [{ tier: null, results }] : []
    }
    const groups: TierGroup[] = []
    for (const result of results) {
        const tier: Tier = result.distance <= cutoff ? 'top' : 'other'
        const last = groups[groups.length - 1]
        if (last && last.tier === tier) {
            last.results.push(result)
        } else {
            groups.push({ tier, results: [result] })
        }
    }
    return groups
}
