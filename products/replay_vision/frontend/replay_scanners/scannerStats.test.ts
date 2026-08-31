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

    // Mirrors a fresh scanner: enabled, able to scan, and created moments ago.
    const scannerWith = (
        overrides: Partial<{
            enabled: boolean
            created_at: string
            limit_reached: boolean
            sampling_rate: number
        }> = {}
    ): Parameters<typeof isAwaitingFirstResults>[1] => ({
        enabled: true,
        created_at: NOW.subtract(2, 'minute').toISOString(),
        limit_reached: false,
        sampling_rate: 1,
        ...overrides,
    })

    const cases: [string, ObservationStatsApi | null, Parameters<typeof isAwaitingFirstResults>[1], boolean][] = [
        // The reported bug: a slow, failing, or not-yet-loaded stats call must not drop a fresh scanner
        // out of pending, or the generic "no matching events" empty state flashes on the status page.
        ['stats not loaded yet stays pending', null, scannerWith(), true],
        ['fresh scanner with no settled observations', statsWith({}), scannerWith(), true],
        ['first observations still processing', statsWith({ total: 2, in_flight: 2 }), scannerWith(), true],
        ['settled observations exist', statsWith({ total: 1, succeeded: 1 }), scannerWith(), false],
        ['scanner disabled', statsWith({}), scannerWith({ enabled: false }), false],
        // A cap below one observation's cost, or a sampling-rate pause, blocks scans from the first
        // second, so the panel must not promise a first scan that can never run.
        ['credit limit already reached', statsWith({}), scannerWith({ limit_reached: true }), false],
        ['sampling paused at 0', statsWith({}), scannerWith({ sampling_rate: 0 }), false],
        [
            'past the first hour degrades to the normal empty state',
            statsWith({}),
            scannerWith({ created_at: NOW.subtract(2, 'hour').toISOString() }),
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
