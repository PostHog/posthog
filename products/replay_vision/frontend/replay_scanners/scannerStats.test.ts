import type { ObservationStatsApi } from '../generated/api.schemas'
import { deriveSummarizerFacetStats } from './scannerStats'

// Partial on purpose: only the fields deriveSummarizerFacetStats reads.
const stats = {
    status_counts: { total: 10, succeeded: 8, failed: 1, ineligible: 1, in_flight: 0, success_rate: 0.8 },
    summarizer: {
        friction_ranked: [{ term: 'checkout stalls', count: 3 }],
        keyword_ranked: [{ term: 'checkout', count: 5 }],
        total_with_facets: 4,
        total_with_friction: 3,
    },
} as ObservationStatsApi

describe('deriveSummarizerFacetStats', () => {
    it('uses every succeeded summary as the friction rate denominator, not just facet emitters', () => {
        expect(deriveSummarizerFacetStats(stats)).toEqual({
            frictionRanked: [['checkout stalls', 3]],
            keywordRanked: [['checkout', 5]],
            totalSucceeded: 8,
            totalWithFriction: 3,
        })
    })

    it('returns empty stats while the API response has not loaded', () => {
        expect(deriveSummarizerFacetStats(null)).toEqual({
            frictionRanked: [],
            keywordRanked: [],
            totalSucceeded: 0,
            totalWithFriction: 0,
        })
    })
})
