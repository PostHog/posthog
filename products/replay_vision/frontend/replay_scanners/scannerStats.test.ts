import { dayjs } from 'lib/dayjs'

import type { ObservationStatsApi } from '../generated/api.schemas'
import { deriveSummarizerFacetStats, isAwaitingFirstResults } from './scannerStats'

// Fully typed (no cast) so schema changes to ObservationStatsApi break these fixtures at compile time.
const emptyStats: ObservationStatsApi = {
    status_counts: { total: 0, succeeded: 0, failed: 0, ineligible: 0, in_flight: 0, success_rate: null },
    coverage: { recent_sessions: 0, total_sessions: 0, recent_days: 14 },
    labels: { up_total: 0, down_total: 0, by_day: [], by_rating_day: [], version_markers: [] },
    available_tags: [],
    monitor: null,
    classifier: null,
    scorer: null,
    summarizer: null,
}

const stats: ObservationStatsApi = {
    ...emptyStats,
    status_counts: { total: 10, succeeded: 8, failed: 1, ineligible: 1, in_flight: 0, success_rate: 0.8 },
    summarizer: {
        friction_ranked: [{ term: 'checkout stalls', count: 3 }],
        keyword_ranked: [{ term: 'checkout', count: 5 }],
        total_with_facets: 4,
        total_with_friction: 3,
    },
}

describe('isAwaitingFirstResults', () => {
    const NOW = dayjs('2026-08-11T12:00:00Z')

    const statsWith = (counts: Partial<ObservationStatsApi['status_counts']>): ObservationStatsApi => ({
        ...emptyStats,
        status_counts: { ...emptyStats.status_counts, ...counts },
    })

    // Mirrors a fresh scanner: created moments ago, watermark seeded 35 minutes before creation.
    const scannerWith = (
        overrides: Partial<{ enabled: boolean; created_at: string; last_swept_at: string }> = {}
    ): Parameters<typeof isAwaitingFirstResults>[1] => ({
        enabled: true,
        created_at: NOW.subtract(2, 'minute').toISOString(),
        last_swept_at: NOW.subtract(37, 'minute').toISOString(),
        ...overrides,
    })

    const cases: [string, ObservationStatsApi | null, Parameters<typeof isAwaitingFirstResults>[1], boolean][] = [
        ['stats not loaded yet', null, scannerWith(), false],
        ['fresh scanner before its first sweep completes', statsWith({}), scannerWith(), true],
        [
            'first observations still processing after the sweep',
            statsWith({ total: 2, in_flight: 2 }),
            scannerWith({ last_swept_at: NOW.subtract(1, 'minute').toISOString() }),
            true,
        ],
        ['settled observations exist', statsWith({ total: 1, succeeded: 1 }), scannerWith(), false],
        [
            'first sweep done and genuinely nothing matched',
            statsWith({}),
            scannerWith({ last_swept_at: NOW.subtract(1, 'minute').toISOString() }),
            false,
        ],
        ['scanner disabled', statsWith({}), scannerWith({ enabled: false }), false],
        [
            'stalled sweep past the first hour degrades to the normal empty state',
            statsWith({}),
            scannerWith({
                created_at: NOW.subtract(2, 'hour').toISOString(),
                last_swept_at: NOW.subtract(3, 'hour').toISOString(),
            }),
            false,
        ],
    ]

    it.each(cases)('%s', (_label, stats, scanner, expected) => {
        expect(isAwaitingFirstResults(stats, scanner, NOW)).toBe(expected)
    })
})

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
