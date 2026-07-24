import { describe, expect, it } from 'vitest'

import type { CatalogMetricSummary } from '@/api/client'
import { searchCatalogMetrics } from '@/tools/metric-search'

function metric(overrides: Partial<CatalogMetricSummary>): CatalogMetricSummary {
    return {
        name: 'a_metric',
        display_name: 'A metric',
        description: '',
        status: 'approved',
        is_drifted: false,
        ...overrides,
    }
}

describe('searchCatalogMetrics', () => {
    it('ranks a name hit above a description-only hit and carries the trust fields', () => {
        const metrics = [
            metric({ name: 'weekly_signups', display_name: 'Weekly signups', description: 'includes revenue context' }),
            metric({
                name: 'monthly_recurring_revenue',
                display_name: 'MRR',
                description: 'sum of paid bills',
                status: 'proposed',
                is_drifted: true,
            }),
        ]

        const results = searchCatalogMetrics(metrics, 'revenue')

        expect(results.map((m) => m.name)).toEqual(['monthly_recurring_revenue', 'weekly_signups'])
        // The trust state travels with the hit so the model can still reject a proposed/drifted metric.
        expect(results[0]).toMatchObject({ status: 'proposed', is_drifted: true })
    })

    it('excludes metrics that match no query token', () => {
        const metrics = [metric({ name: 'monthly_recurring_revenue', display_name: 'MRR', description: 'paid bills' })]
        expect(searchCatalogMetrics(metrics, 'retention')).toEqual([])
    })

    it('caps the number of returned matches', () => {
        const metrics = Array.from({ length: 8 }, (_, i) =>
            metric({ name: `revenue_metric_${i}`, display_name: 'rev' })
        )
        expect(searchCatalogMetrics(metrics, 'revenue', 5)).toHaveLength(5)
    })
})
