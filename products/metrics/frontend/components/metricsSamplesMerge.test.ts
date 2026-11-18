import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import { mergeSamples } from './metricsSamplesMerge'

const sample = (metric: string, timestamp: string, attributes: Record<string, string> = {}): _MetricEventSampleApi => ({
    timestamp,
    metric_name: metric,
    metric_type: 'sum',
    value: 1,
    count: 1,
    unit: '',
    aggregation_temporality: 'cumulative',
    is_monotonic: true,
    service_name: 'checkout',
    trace_id: '',
    span_id: '',
    attributes,
    resource_attributes: {},
})

const secondsAfter = (seconds: number): string => new Date(Date.UTC(2026, 6, 9, 5, 0, seconds)).toISOString()

describe('mergeSamples', () => {
    it('lists an emission that two overlapping series return once, tagged with both, and keeps other metric types apart', () => {
        const prod = sample('requests', secondsAfter(10), { env: 'prod' })
        const dev = sample('requests', secondsAfter(5), { env: 'dev' })
        const prodGauge = { ...prod, metric_type: 'gauge' }

        const rows = mergeSamples(
            [
                { clauses: ['a'], samples: [prod, dev] },
                { clauses: ['b'], samples: [{ ...prod }] },
                { clauses: ['c'], samples: [prodGauge] },
            ],
            50
        )

        expect(rows.map((row) => [row.attributes.env, row.metric_type, row.clauses])).toEqual([
            ['prod', 'sum', ['a', 'b']],
            ['prod', 'gauge', ['c']],
            ['dev', 'sum', ['a']],
        ])
    })

    it('keeps a share of rows for a quiet series that a busy one would push out', () => {
        const busy = Array.from({ length: 10 }, (_, i) => sample('busy', secondsAfter(100 + i)))
        const quiet = [sample('quiet', secondsAfter(1)), sample('quiet', secondsAfter(2))]

        const rows = mergeSamples(
            [
                { clauses: ['a'], samples: busy },
                { clauses: ['b'], samples: quiet },
            ],
            6
        )

        expect(rows.filter((row) => row.metric_name === 'quiet')).toHaveLength(2)
        expect(rows).toHaveLength(6)
    })

    it('orders by instant, not by timestamp text', () => {
        const rows = mergeSamples(
            [
                { clauses: ['a'], samples: [sample('m', '2026-07-09T07:00:00+02:00')] },
                { clauses: ['b'], samples: [sample('n', '2026-07-09T05:30:00+00:00')] },
            ],
            50
        )

        expect(rows.map((row) => row.metric_name)).toEqual(['n', 'm'])
    })
})
