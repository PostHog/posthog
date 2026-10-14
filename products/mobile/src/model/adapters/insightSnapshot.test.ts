import type { InsightApi } from '@/api/insights'

import { insightSnapshot, usesOwnRange } from './insightSnapshot'

const NOW = Date.parse('2026-10-14T12:00:00Z')

function trends(math: string | undefined, display = 'ActionsLineGraph'): unknown {
    return {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'day',
            series: [{ kind: 'EventsNode', event: '$pageview', ...(math ? { math } : {}) }],
            trendsFilter: { display },
            dateRange: { date_from: '-7d' },
        },
    }
}

function insight(overrides: Partial<InsightApi>): InsightApi {
    return {
        id: 7,
        short_id: 'abc123',
        name: 'Signups',
        derived_name: null,
        query: trends(undefined),
        result: [],
        last_refresh: '2026-10-14T11:00:00Z',
        cache_target_age: '2026-10-14T17:00:00Z',
        next_allowed_client_refresh: '2026-10-14T11:15:00Z',
        is_cached: true,
        // The window reaches the end of today, so the last bucket is in progress.
        resolved_date_range: { date_from: '2026-10-11T00:00:00Z', date_to: '2026-10-14T23:59:59Z' },
        ...overrides,
    }
}

const DAYS = ['2026-10-11', '2026-10-12', '2026-10-13', '2026-10-14']
const CONTEXT = { readAt: 1000, serverNow: NOW }

describe('insightSnapshot', () => {
    test.each<[string, Partial<InsightApi>]>([
        [
            'a rate-limited response',
            {
                result: null,
                last_refresh: '2026-10-14T12:00:00Z',
                query_status: { error: true, error_code: 'rate_limited' },
            },
        ],
        ['an error with a result field', { result: [], query_status: { error: true } }],
    ])('keeps the previous freshness and values after %s', (_name, failed) => {
        const good = insightSnapshot(insight({ result: [{ days: DAYS, data: [1, 2, 3, 4] }] }), undefined, CONTEXT)

        const after = insightSnapshot(insight(failed), good, { ...CONTEXT, readAt: 2000 })

        expect(after).toMatchObject({
            lastRefreshAt: '2026-10-14T11:00:00Z',
            nextAllowedRefreshAt: '2026-10-14T11:15:00Z',
            value: good.value,
            readAt: 2000,
            refreshFailed: true,
        })
    })

    test.each<[string, string | undefined, unknown[], Record<string, unknown>]>([
        [
            'the last complete bucket against the one before it, skipping today',
            'dau',
            [{ days: DAYS, data: [10, 20, 30, 5] }],
            { value: 30, valueAt: '2026-10-13', delta: { previous: 20, basis: 'previous_bucket' } },
        ],
        [
            'window totals of a summable series against the previous period',
            undefined,
            [
                { days: DAYS, data: [1, 2, 3, 4], compare_label: 'current', action: { order: 0 } },
                { days: DAYS, data: [1, 1, 1, 1], compare_label: 'previous', action: { order: 0 } },
            ],
            { value: 10, valueAt: null, delta: { previous: 4, basis: 'compare' } },
        ],
        [
            'distinct users bucket by bucket against the previous period, never a sum',
            'weekly_active',
            [
                { days: DAYS, data: [100, 110, 120, 30], compare_label: 'current', action: { order: 0 } },
                { days: DAYS, data: [90, 95, 100, 98], compare_label: 'previous', action: { order: 0 } },
            ],
            { value: 120, valueAt: '2026-10-13', delta: { previous: 100, basis: 'compare' } },
        ],
        [
            'the server aggregate of a big number',
            'dau',
            [{ aggregated_value: 412, action: { order: 0 } }],
            { value: 412, valueAt: null, delta: null },
        ],
    ])('reads %s', (_name, math, result, expected) => {
        const snapshot = insightSnapshot(insight({ query: trends(math), result }), undefined, CONTEXT)

        expect(snapshot).toMatchObject(expected)
    })

    test.each<[string, Record<string, unknown> | null, unknown, boolean]>([
        ['a tile with its own dates', { date_from: '-30d' }, trends(undefined), true],
        ['a tile that ignores dashboard filters', { ignoreDashboardFilters: true }, trends(undefined), true],
        [
            'a SQL tile without the filters placeholder',
            null,
            { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select count() from events' } },
            true,
        ],
        [
            'a SQL tile with the filters placeholder',
            null,
            {
                kind: 'DataVisualizationNode',
                source: { kind: 'HogQLQuery', query: 'select count() from events where { filters }' },
            },
            false,
        ],
        ['a trends tile', null, trends(undefined), false],
    ])('detects %s', (_name, overrides, query, expected) => {
        expect(usesOwnRange(overrides, query)).toBe(expected)
    })
})
