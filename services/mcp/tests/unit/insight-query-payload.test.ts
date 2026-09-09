import { describe, expect, it } from 'vitest'

import { queryHandler } from '@/tools/insights/query'
import { type Context, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY } from '@/tools/types'

const SAVED_QUERY = {
    kind: 'InsightVizNode',
    source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] },
}

const SAVED_INSIGHT = {
    id: 4242,
    short_id: 'AaVQ8Ijw',
    name: 'Overdue alert checks',
    query: SAVED_QUERY,
    filters: { date_from: '-30d' },
    result: [{ data: [1, 2, 3], label: 'cached copy' }],
    columns: ['Date', 'Overdue alert checks'],
    types: ['DateTime', 'UInt64'],
    hogql: 'SELECT 1',
    dashboards: [1, 2],
    dashboard_tiles: [{ id: 9, dashboard_id: 1 }],
    tags: ['alerts'],
    created_by: { id: 7, email: 'someone@example.com' },
    description: 'A saved insight',
}

function mockContext(): Context {
    return {
        stateManager: { getProjectId: async () => '1' },
        api: {
            getProjectBaseUrl: () => 'https://us.posthog.com/project/1',
            insights: () => ({
                get: async () => ({ success: true, data: SAVED_INSIGHT }),
                query: async () => ({
                    success: true,
                    data: {
                        results: [{ data: [1, 2, 3], label: 'live results' }],
                        formatted_results: 'Date|Overdue alert checks\n2026-08-10 00:00|0',
                    },
                }),
            }),
        },
    } as unknown as Context
}

describe('insight-query result payload', () => {
    it('carries the insight identity and link, and the data exactly once', async () => {
        const result = (await queryHandler(mockContext(), {
            insightId: 'AaVQ8Ijw',
            output_format: 'optimized',
        })) as Record<string, any>

        // Exact key set, not a subset: a subset assertion passes with the whole roster attached.
        expect(Object.keys(result.insight).sort()).toEqual(['id', 'name', 'short_id', 'url'])
        expect(result.insight.id).toBe(4242)
        expect(result.insight.short_id).toBe('AaVQ8Ijw')
        expect(result.insight.name).toBe('Overdue alert checks')
        expect(result.insight.url).toContain('/insights/AaVQ8Ijw')

        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('Overdue alert checks')
        expect(result.results).toEqual([{ data: [1, 2, 3], label: 'live results' }])
        expect(result.query).toEqual(SAVED_QUERY.source)
    })
})
