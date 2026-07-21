import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Schemas } from '@/api/generated'
import {
    createGovernedMetricsSearcher,
    MAX_METRIC_SEARCH_RESULTS,
    type MetricSearchDeps,
    type MetricSearchOutcome,
} from '@/tools/metric-search'

function metric(overrides: Partial<Schemas.DataCatalogMetric>): Schemas.DataCatalogMetric {
    return {
        id: 'id',
        name: 'metric',
        display_name: '',
        description: '',
        owner: null,
        definition_kind: 'HogQLQuery',
        referenced_table_names: [],
        status: 'approved',
        is_drifted: false,
        approved_at: null,
        approved_by: null,
        last_run_at: null,
        created_by: { id: 1 } as Schemas.UserBasic,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: null,
        ...overrides,
    } as Schemas.DataCatalogMetric
}

function envelope(results: Schemas.DataCatalogMetric[]): Schemas.PaginatedDataCatalogMetricList {
    return { count: results.length, next: null, previous: null, results }
}

function makeDeps(request: (opts: unknown) => Promise<unknown>): MetricSearchDeps {
    return {
        stateManager: { getProjectId: async () => '2' },
        api: { request },
    } as MetricSearchDeps
}

describe('metric-search', () => {
    afterEach(() => {
        vi.useRealTimers()
    })

    it('ranks metrics for a plain-word query, name hits above description-only hits', async () => {
        const metrics = [
            metric({ name: 'weekly_signups', description: 'Signups per week' }),
            metric({
                name: 'top_customers_mrr_by_business_model',
                display_name: 'Top customers by MRR',
                description: 'Ranks customers by monthly recurring revenue',
            }),
            metric({ name: 'churn_rate', description: 'Mentions revenue only in passing here' }),
        ]
        const searcher = createGovernedMetricsSearcher(makeDeps(async () => envelope(metrics)))

        const matches = await searcher('mrr revenue customers')

        expect(matches.map((m) => m.name)).toEqual(['top_customers_mrr_by_business_model', 'churn_rate'])
        expect(matches[0]).toMatchObject({
            display_name: 'Top customers by MRR',
            status: 'approved',
            is_drifted: false,
        })
    })

    it('routes a metacharacter query through the regex predicate and matches on name', async () => {
        const metrics = [
            metric({ name: 'mrr_expansion', description: 'Expansion revenue' }),
            metric({ name: 'weekly_signups', description: 'Signups per week' }),
        ]
        const searcher = createGovernedMetricsSearcher(makeDeps(async () => envelope(metrics)))

        const matches = await searcher('mrr.*')

        expect(matches.map((m) => m.name)).toEqual(['mrr_expansion'])
    })

    it('reads the DRF paginated envelope and requests an explicit high limit', async () => {
        const request = vi.fn().mockResolvedValue(envelope([metric({ name: 'arr_total', description: 'ARR' })]))
        const searcher = createGovernedMetricsSearcher(makeDeps(request))

        const matches = await searcher('arr')

        expect(matches).toHaveLength(1)
        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'GET',
                path: expect.stringContaining('/data_catalog/metrics/'),
                query: expect.objectContaining({ limit: expect.any(Number) }),
            })
        )
    })

    it.each([
        ['http error', () => Promise.reject(Object.assign(new Error('forbidden'), { status: 403 }))],
        ['network error', () => Promise.reject(new TypeError('fetch failed'))],
        ['invalid regex query', async () => envelope([metric({ name: 'mrr_total', description: 'MRR' })])],
    ])('resolves to an empty array on %s', async (_label, request) => {
        const outcomes: MetricSearchOutcome[] = []
        const searcher = createGovernedMetricsSearcher(makeDeps(request as () => Promise<unknown>), {
            onOutcome: (outcome) => outcomes.push(outcome),
        })

        const query = _label === 'invalid regex query' ? '(unclosed' : 'revenue'
        await expect(searcher(query)).resolves.toEqual([])
        expect(outcomes[0]?.status).not.toBe('ok')
    })

    it('resolves to an empty array within the bound when the request never settles', async () => {
        vi.useFakeTimers()
        const outcomes: MetricSearchOutcome[] = []
        const searcher = createGovernedMetricsSearcher(
            makeDeps(() => new Promise(() => {})),
            { timeoutMs: 2000, onOutcome: (outcome) => outcomes.push(outcome) }
        )

        const pending = searcher('revenue')
        await vi.advanceTimersByTimeAsync(2001)

        await expect(pending).resolves.toEqual([])
        expect(outcomes[0]?.status).toBe('timeout')
    })

    it('caps results and truncates long descriptions', async () => {
        const longDescription = 'revenue '.repeat(60).trim()
        const metrics = Array.from({ length: MAX_METRIC_SEARCH_RESULTS + 3 }, (_, i) =>
            metric({ name: `revenue_metric_${i}`, description: longDescription })
        )
        const searcher = createGovernedMetricsSearcher(makeDeps(async () => envelope(metrics)))

        const matches = await searcher('revenue')

        expect(matches).toHaveLength(MAX_METRIC_SEARCH_RESULTS)
        for (const match of matches) {
            expect(match.description.length).toBeLessThanOrEqual(201)
        }
    })

    it('coalesces null display_name and description instead of throwing', async () => {
        const rows = [
            { ...metric({ name: 'mrr_total' }), display_name: null, description: null },
        ] as unknown as Schemas.DataCatalogMetric[]
        const searcher = createGovernedMetricsSearcher(makeDeps(async () => envelope(rows)))

        const matches = await searcher('mrr.*')

        expect(matches).toEqual([
            { name: 'mrr_total', display_name: '', description: '', status: 'approved', is_drifted: false },
        ])
    })
})
