import type { ObservationStatsApi } from '../generated/api.schemas'
import { deriveClassifierTagStats, deriveSummarizerFacetStats } from './scannerStats'

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

describe('deriveClassifierTagStats', () => {
    it('maps per-tag person-backed users so the cohort button can gate on them', () => {
        const stats = {
            classifier: {
                // `bug` has a person-backed user; `ux` was seen only on unidentified recordings.
                fixed_ranked: [
                    { tag: 'bug', count: 4, users: 2 },
                    { tag: 'ux', count: 3, users: 0 },
                ],
                // Older responses (pre-regeneration) omit `users`; it must surface as undefined, not 0.
                freeform_ranked: [{ tag: 'surprise', count: 1 }],
                total_with_tags: 8,
            },
        } as unknown as ObservationStatsApi

        const derived = deriveClassifierTagStats(stats)

        expect(derived.fixedRanked).toEqual([
            ['bug', 4],
            ['ux', 3],
        ])
        expect(derived.fixedTagUsers).toEqual({ bug: 2, ux: 0 })
        expect(derived.freeformTagUsers).toEqual({ surprise: undefined })
    })
})
